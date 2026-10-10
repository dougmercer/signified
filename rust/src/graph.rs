//! Graph state and the propagation algorithm: dependency tracking, push
//! invalidation and pull refresh.
//!
//! Edges are stored twice. A consumer (computed or effect) keeps its
//! dependencies in `deps`, in the order it first read them. Each dependency
//! keeps its consumers in `observers`. A dependency link records its slot in
//! the dependency's observer list, and that entry records the link's position,
//! so either side can find the other in constant time. Removed observers leave
//! a vacant slot until the list compacts, which keeps notification order.

use std::cell::{Cell, RefCell};
use std::collections::{HashSet, VecDeque};
use std::rc::{Rc, Weak};
use std::sync::OnceLock;

use pyo3::exceptions::{PyException, PyRecursionError, PyRuntimeError, PyTypeError};
use pyo3::gc::PyVisit;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyBytes, PyComplex, PyFloat, PyInt, PyString, PyTuple, PyWeakrefReference,
};
use pyo3::PyTraverseError;

use crate::classes::{ComputedCore, SignalCore};
use crate::config;
use crate::effects::{self, Job};

// ---------------------------------------------------------------------------
// Graph state
// ---------------------------------------------------------------------------

/// Staleness of a computed node, ordered by invalidation priority.
/// `Uninitialized` sits above `MustRefresh` so invalidation never downgrades a
/// node that has not computed yet.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub(crate) enum State {
    Fresh,
    Stale,
    MustRefresh,
    Uninitialized,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum Kind {
    Signal,
    Computed,
    Effect,
}

pub(crate) const NEVER: u64 = u64::MAX;
const NO_SLOT: u32 = u32::MAX;

/// Observer lists at least this long compact once half their slots are vacant.
const COMPACT_MIN_LEN: usize = 16;

/// `Rc<Node>` made `Send` and `Sync` so a Python object can own one.
///
/// SAFETY: nodes are only touched while attached to an interpreter that holds
/// the GIL, which lets one thread run at a time (the module is
/// `gil_used = true`), so the non-atomic reference counts and the cells are
/// never accessed concurrently. No borrow is held across a call into Python,
/// so a thread switch inside such a call never observes a cell mid-update.
/// Concurrent use from several threads is unsupported, but it cannot cause a
/// data race.
pub(crate) struct Shared(pub(crate) Rc<Node>);

unsafe impl Send for Shared {}
unsafe impl Sync for Shared {}

impl std::ops::Deref for Shared {
    type Target = Rc<Node>;

    fn deref(&self) -> &Rc<Node> {
        &self.0
    }
}

/// An entry in a node's observer list.
pub(crate) enum Observer {
    /// A removed entry, dropped when the list compacts.
    Vacant,
    /// A computed or effect; `link` is the position of its link to this node.
    Consumer { node: Weak<Node>, link: u32 },
    /// An object passed to `subscribe()`, held weakly. `id` is its address,
    /// compared before the weak reference is resolved.
    Python {
        reference: Py<PyWeakrefReference>,
        id: usize,
    },
}

/// How a computed node or effect produces its value.
pub(crate) enum Compute {
    /// A zero-argument Python callable.
    Function(Py<PyAny>),
    /// `func(*resolved args)`, with reactive arguments resolved in Rust.
    Call {
        func: Py<PyAny>,
        args: Vec<Py<PyAny>>,
    },
    /// A `Binding`: read the holder signal, then the source it holds.
    Source(Py<PyAny>),
}

impl Compute {
    pub(crate) fn clone_ref(&self, py: Python<'_>) -> Compute {
        match self {
            Compute::Function(f) => Compute::Function(f.clone_ref(py)),
            Compute::Call { func, args } => Compute::Call {
                func: func.clone_ref(py),
                args: args.iter().map(|arg| arg.clone_ref(py)).collect(),
            },
            Compute::Source(holder) => Compute::Source(holder.clone_ref(py)),
        }
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        match self {
            Compute::Function(f) => visit.call(f),
            Compute::Call { func, args } => {
                visit.call(func)?;
                for arg in args {
                    visit.call(arg)?;
                }
                Ok(())
            }
            Compute::Source(holder) => visit.call(holder),
        }
    }
}

/// Which consumer last read a node during a run, and where that consumer's
/// link to the node is.
#[derive(Clone, Copy, PartialEq, Eq)]
struct ReaderLink {
    reader: usize,
    position: u32,
}

const NO_READER: ReaderLink = ReaderLink {
    reader: 0,
    position: 0,
};

/// Edge from a consumer to one dependency, reused across runs.
pub(crate) struct DepLink {
    pub(crate) node: Rc<Node>,
    /// The dependency's Python object; keeps it alive and is visible to the GC.
    pub(crate) handle: Py<PyAny>,
    version: u64,
    read_version: u64,
    seen: u64,
    /// This consumer's entry in `node.observers`, once subscribed.
    slot: Cell<u32>,
    /// `node.reader_link` before this run, restored when the run ends.
    rollback: Cell<ReaderLink>,
}

/// A failed evaluation, kept as Python objects so the GC can traverse it.
pub(crate) struct CachedError {
    exception: Py<PyAny>,
    traceback: Option<Py<PyAny>>,
}

/// What a `Binding` returns to after `at()`, if its source is unchanged.
pub(crate) struct RestorePoint {
    pub(crate) value: Py<PyAny>,
    pub(crate) version: u64,
    pub(crate) holder: Rc<Node>,
    pub(crate) source: Py<PyAny>,
    pub(crate) source_node: Rc<Node>,
    pub(crate) source_version: u64,
}

pub(crate) struct Node {
    pub(crate) kind: Kind,
    pub(crate) version: Cell<u64>,
    pub(crate) value: RefCell<Option<Py<PyAny>>>,
    pub(crate) equal: RefCell<Option<Py<PyAny>>>,
    pub(crate) name: RefCell<Option<Py<PyAny>>>,
    observers: RefCell<Vec<Observer>>,
    vacant: Cell<u32>,
    /// Set while a consumer that reads this node runs; see `register_dependency`.
    reader_link: Cell<ReaderLink>,
    /// State for computeds and effects; `None` for signals.
    consumer: Option<Box<Consumer>>,
}

/// The part of a node that reads other nodes: computeds and effects.
pub(crate) struct Consumer {
    pub(crate) compute: RefCell<Option<Compute>>,
    pub(crate) state: Cell<State>,
    computing: Cell<bool>,
    pub(crate) notified: Cell<bool>,
    clock_seen: Cell<u64>,
    token: Cell<u64>,
    deps: RefCell<Vec<DepLink>>,
    pub(crate) error: RefCell<Option<CachedError>>,
    pub(crate) restore: RefCell<Option<RestorePoint>>,
    /// Effects only: not disposed.
    pub(crate) active: Cell<bool>,
    /// Effects only: has run at least once.
    pub(crate) has_run: Cell<bool>,
    /// Effects only: the queue sequence number while queued, else 0.
    pub(crate) queued: Cell<u64>,
    /// Effects only: runs in the flush numbered `run_epoch`.
    pub(crate) runs: Cell<u32>,
    pub(crate) run_epoch: Cell<u64>,
}

impl Node {
    pub(crate) fn new(kind: Kind) -> Node {
        let consumer = match kind {
            Kind::Signal => None,
            Kind::Computed | Kind::Effect => Some(Box::new(Consumer {
                compute: RefCell::new(None),
                state: Cell::new(if kind == Kind::Computed {
                    State::Uninitialized
                } else {
                    State::Fresh
                }),
                computing: Cell::new(false),
                notified: Cell::new(false),
                clock_seen: Cell::new(NEVER),
                token: Cell::new(0),
                deps: RefCell::new(Vec::new()),
                error: RefCell::new(None),
                restore: RefCell::new(None),
                active: Cell::new(false),
                has_run: Cell::new(false),
                queued: Cell::new(0),
                runs: Cell::new(0),
                run_epoch: Cell::new(0),
            })),
        };
        Node {
            kind,
            version: Cell::new(0),
            value: RefCell::new(None),
            equal: RefCell::new(None),
            name: RefCell::new(None),
            observers: RefCell::new(Vec::new()),
            vacant: Cell::new(0),
            reader_link: Cell::new(NO_READER),
            consumer,
        }
    }

    /// The consumer state of a computed or effect.
    pub(crate) fn consumer(&self) -> &Consumer {
        self.consumer
            .as_deref()
            .expect("only computeds and effects read other nodes")
    }

    /// Visit every Python object this node owns; busy cells are skipped.
    pub(crate) fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        for cell in [&self.value, &self.equal] {
            if let Ok(object) = cell.try_borrow() {
                if let Some(object) = object.as_ref() {
                    visit.call(object)?;
                }
            }
        }
        let Some(consumer) = self.consumer.as_deref() else {
            return Ok(());
        };
        if let Ok(compute) = consumer.compute.try_borrow() {
            if let Some(compute) = compute.as_ref() {
                compute.traverse(visit)?;
            }
        }
        if let Ok(error) = consumer.error.try_borrow() {
            if let Some(cached) = error.as_ref() {
                visit.call(&cached.exception)?;
                if let Some(traceback) = cached.traceback.as_ref() {
                    visit.call(traceback)?;
                }
            }
        }
        if let Ok(deps) = consumer.deps.try_borrow() {
            for link in deps.iter() {
                visit.call(&link.handle)?;
            }
        }
        if let Ok(restore) = consumer.restore.try_borrow() {
            if let Some(point) = restore.as_ref() {
                visit.call(&point.value)?;
                visit.call(&point.source)?;
            }
        }
        Ok(())
    }

    /// Drop every Python object this node owns (for `__clear__`).
    pub(crate) fn clear(self: &Rc<Self>) {
        detach_all_deps(self);
        let value = self.value.take();
        let equal = self.equal.take();
        let name = self.name.take();
        let consumer = self.consumer.as_deref().map(|consumer| {
            (
                consumer.compute.take(),
                consumer.error.take(),
                consumer.restore.take(),
            )
        });
        drop((value, equal, name, consumer));
    }
}

impl Drop for Node {
    /// A freed consumer unsubscribes from its dependencies right away.
    fn drop(&mut self) {
        let key = self as *const Node as usize;
        if let Some(consumer) = self.consumer.as_mut() {
            let links = std::mem::take(consumer.deps.get_mut());
            unlink(key, &links);
            // Dropping the links can free dependencies and run Python code;
            // nothing is borrowed here.
            drop(links);
        }
    }
}

// ---------------------------------------------------------------------------
// Runtime: version clock, tracking frames, notification depth, effect queue
// ---------------------------------------------------------------------------

pub(crate) struct Runtime {
    clock: Cell<u64>,
    /// The consumer being evaluated, innermost last; `None` marks an untracked block.
    frames: RefCell<Vec<Option<Rc<Node>>>>,
    /// Nesting of notification walks; effects run when it returns to zero.
    pub(crate) wave_depth: Cell<u32>,
    /// Classes whose `.value` is the engine's own getter (see `resolve_arg`).
    standard_types: RefCell<Vec<Py<PyAny>>>,
    /// Effects and observers waiting to run, in the order they were queued.
    pub(crate) pending: RefCell<VecDeque<Job>>,
    pub(crate) pending_seq: Cell<u64>,
    /// Weak references of observers already in `pending`.
    pub(crate) queued_observers: RefCell<HashSet<usize>>,
    pub(crate) flush_epoch: Cell<u64>,
    pub(crate) batch_depth: Cell<u32>,
    pub(crate) flushing: Cell<bool>,
    /// The plugin manager's `hook` object, when hooks are on.
    pub(crate) hooks: RefCell<Option<Py<PyAny>>>,
    pub(crate) hooks_on: Cell<bool>,
    pub(crate) migration_warnings: Cell<bool>,
}

// SAFETY: as for `Shared`; one runtime is shared by all threads, like a
// module's globals, and the GIL serializes access.
unsafe impl Send for Runtime {}
unsafe impl Sync for Runtime {}

pub(crate) fn rt() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(|| Runtime {
        clock: Cell::new(0),
        frames: RefCell::new(Vec::new()),
        wave_depth: Cell::new(0),
        standard_types: RefCell::new(Vec::new()),
        pending: RefCell::new(VecDeque::new()),
        pending_seq: Cell::new(0),
        queued_observers: RefCell::new(HashSet::new()),
        flush_epoch: Cell::new(0),
        batch_depth: Cell::new(0),
        flushing: Cell::new(false),
        hooks: RefCell::new(None),
        hooks_on: Cell::new(false),
        migration_warnings: Cell::new(false),
    })
}

fn clock() -> u64 {
    rt().clock.get()
}

/// Advance the global version clock.
pub(crate) fn bump_clock() -> u64 {
    let rt = rt();
    let version = rt.clock.get() + 1;
    rt.clock.set(version);
    version
}

/// Advance the clock and stamp `node` with the new version. Versions are
/// unique across nodes and never reused.
pub(crate) fn bump_version(node: &Node) -> u64 {
    let version = bump_clock();
    node.version.set(version);
    version
}

pub(crate) fn push_frame(frame: Option<Rc<Node>>) {
    rt().frames.borrow_mut().push(frame);
}

pub(crate) fn pop_frame() -> Option<Option<Rc<Node>>> {
    rt().frames.borrow_mut().pop()
}

/// Whether the innermost frame is an untracked block.
pub(crate) fn in_untracked_block() -> bool {
    matches!(rt().frames.borrow().last(), Some(None))
}

/// Whether a read right now would register a dependency.
pub(crate) fn is_tracking() -> bool {
    matches!(rt().frames.borrow().last(), Some(Some(_)))
}

pub(crate) fn register_standard_type(ty: Py<PyAny>) {
    rt().standard_types.borrow_mut().push(ty);
}

pub(crate) fn is_standard_type(ty: &Bound<'_, PyAny>) -> bool {
    let ptr = ty.as_ptr();
    rt().standard_types
        .borrow()
        .iter()
        .any(|standard| standard.as_ptr() == ptr)
}

/// Native stack to keep free for the Python code a refresh may call.
const MIN_FREE_STACK: usize = 256 * 1024;

/// Holds one level of Python's recursion budget, so a very deep graph raises
/// `RecursionError` instead of overflowing the native stack. Python 3.12 and
/// 3.13 count calls rather than measuring the stack, and worker threads have
/// small stacks, so the remaining stack is checked directly as well.
struct RecursionGuard;

impl RecursionGuard {
    fn enter(py: Python<'_>) -> PyResult<RecursionGuard> {
        if stacker::remaining_stack().is_some_and(|free| free < MIN_FREE_STACK) {
            return Err(PyRecursionError::new_err(
                "maximum recursion depth exceeded while refreshing a reactive value",
            ));
        }
        let failed = unsafe {
            pyo3::ffi::Py_EnterRecursiveCall(c" while refreshing a reactive value".as_ptr())
        };
        if failed != 0 {
            return Err(PyErr::fetch(py));
        }
        Ok(RecursionGuard)
    }
}

impl Drop for RecursionGuard {
    fn drop(&mut self) {
        unsafe { pyo3::ffi::Py_LeaveRecursiveCall() };
    }
}

// ---------------------------------------------------------------------------
// Observer lists
// ---------------------------------------------------------------------------

fn node_key(node: &Node) -> usize {
    node as *const Node as usize
}

fn has_observers(node: &Node) -> bool {
    node.observers.borrow().len() > node.vacant.get() as usize
}

fn push_observer(node: &Node, observer: Observer) -> u32 {
    let mut observers = node.observers.borrow_mut();
    observers.push(observer);
    (observers.len() - 1) as u32
}

/// Remove the observer in `slot` without compacting, and return it so the
/// caller drops it with nothing borrowed.
fn take_slot(node: &Node, slot: u32) -> Observer {
    let removed = match node.observers.borrow_mut().get_mut(slot as usize) {
        Some(entry) => std::mem::replace(entry, Observer::Vacant),
        None => Observer::Vacant,
    };
    if !matches!(removed, Observer::Vacant) {
        node.vacant.set(node.vacant.get() + 1);
    }
    removed
}

/// Remove the observer in `slot`, compacting the list if it got sparse.
fn vacate(node: &Node, slot: u32) -> Observer {
    let removed = take_slot(node, slot);
    compact_if_sparse(node);
    removed
}

/// Remove the consumer `key`'s entry in `dep`'s observer list, if `slot`
/// still holds it.
fn unsubscribe_consumer(dep: &Node, slot: u32, key: usize) {
    let owned = matches!(
        dep.observers.borrow().get(slot as usize),
        Some(Observer::Consumer { node, .. }) if node.as_ptr() as usize == key
    );
    if owned {
        drop(vacate(dep, slot));
    }
}

/// Drop vacant slots once they make up half of a long list. Consumers whose
/// entries move get their links' slots updated. Not during a notification
/// walk, which iterates the lists by position.
fn compact_if_sparse(node: &Node) {
    let vacant = node.vacant.get() as usize;
    let len = node.observers.borrow().len();
    let all_vacant = vacant == len;
    if rt().wave_depth.get() > 0 || !(all_vacant || (len >= COMPACT_MIN_LEN && vacant * 2 > len)) {
        return;
    }
    let mut observers = node.observers.borrow_mut();
    let mut write = 0;
    for read in 0..observers.len() {
        if matches!(observers[read], Observer::Vacant) {
            continue;
        }
        if read != write {
            observers.swap(read, write);
            if let Observer::Consumer {
                node: consumer,
                link,
            } = &observers[write]
            {
                if let Some(consumer) = consumer.upgrade() {
                    if let Some(link) = consumer.consumer().deps.borrow().get(*link as usize) {
                        link.slot.set(write as u32);
                    }
                }
            }
        }
        write += 1;
    }
    // Only vacant entries are truncated, so nothing Python is dropped here.
    observers.truncate(write);
    node.vacant.set(0);
}

/// Unsubscribe a consumer (identified by `key`) from each of `links`, and
/// undo `register_dependency` bookkeeping that still points at it.
fn unlink(key: usize, links: &[DepLink]) {
    for link in links.iter().rev() {
        if link.node.reader_link.get().reader == key {
            link.node.reader_link.set(link.rollback.get());
        }
        let slot = link.slot.get();
        if slot != NO_SLOT {
            unsubscribe_consumer(&link.node, slot, key);
        }
    }
}

// ---------------------------------------------------------------------------
// Dependency tracking
// ---------------------------------------------------------------------------

fn track_read(node: &Rc<Node>, handle: &Bound<'_, PyAny>) {
    let frames = rt().frames.borrow();
    if let Some(Some(reader)) = frames.last() {
        // Self-reads would make a node depend on itself.
        if !Rc::ptr_eq(reader, node) {
            register_dependency(reader, node, handle);
        }
    }
}

/// Stamp `dep`'s link with the current run, adding the link if needed. While
/// a consumer runs, each of its dependencies records where its link is, so the
/// lookup needs no search. Only Rust allocations happen here, so holding
/// borrows is safe.
fn register_dependency(reader: &Rc<Node>, dep: &Rc<Node>, handle: &Bound<'_, PyAny>) {
    let consumer = reader.consumer();
    let token = consumer.token.get();
    let read_version = dep.version.get();
    let key = node_key(reader);
    let current = dep.reader_link.get();
    let mut deps = consumer.deps.borrow_mut();
    if current.reader == key {
        if let Some(link) = deps.get_mut(current.position as usize) {
            if Rc::ptr_eq(&link.node, dep) {
                link.seen = token;
                link.read_version = read_version;
                return;
            }
        }
    }
    let position = deps.len() as u32;
    deps.push(DepLink {
        node: dep.clone(),
        handle: handle.clone().unbind(),
        version: NEVER,
        read_version,
        seen: token,
        slot: Cell::new(NO_SLOT),
        rollback: Cell::new(current),
    });
    dep.reader_link.set(ReaderLink {
        reader: key,
        position,
    });
}

/// Begin a run: new token, and point each dependency at its link.
pub(crate) fn start_refresh(node: &Rc<Node>) {
    let consumer = node.consumer();
    consumer.token.set(consumer.token.get() + 1);
    let reader = node_key(node);
    for (position, link) in consumer.deps.borrow().iter().enumerate() {
        link.rollback.set(link.node.reader_link.get());
        link.node.reader_link.set(ReaderLink {
            reader,
            position: position as u32,
        });
    }
}

/// End a run: subscribe to every dependency it read and drop the rest. Runs
/// after successful and failed runs alike, so a consumer always depends on
/// exactly what its last run read.
pub(crate) fn commit_refresh(reader: &Rc<Node>) {
    let consumer = reader.consumer();
    let token = consumer.token.get();
    let mut subscribe: Vec<(Rc<Node>, u32)> = Vec::new();
    let mut moved: Vec<(Rc<Node>, u32, u32)> = Vec::new();
    let dropped = {
        let mut deps = consumer.deps.borrow_mut();
        // Undo `start_refresh` and `register_dependency`, innermost first.
        for link in deps.iter().rev() {
            link.node.reader_link.set(link.rollback.get());
        }
        // Keep links read this run, in order, at the front.
        let mut write = 0;
        for read in 0..deps.len() {
            if deps[read].seen != token {
                continue;
            }
            if read != write {
                deps.swap(read, write);
            }
            let link = &mut deps[write];
            link.version = link.read_version;
            let slot = link.slot.get();
            if slot == NO_SLOT {
                subscribe.push((link.node.clone(), write as u32));
            } else if read != write {
                moved.push((link.node.clone(), slot, write as u32));
            }
            write += 1;
        }
        deps.split_off(write)
    };
    for (dep, slot, position) in moved {
        if let Some(Observer::Consumer { link, .. }) =
            dep.observers.borrow_mut().get_mut(slot as usize)
        {
            *link = position;
        }
    }
    let key = node_key(reader);
    for link in &dropped {
        let slot = link.slot.get();
        if slot != NO_SLOT {
            unsubscribe_consumer(&link.node, slot, key);
        }
    }
    for (dep, position) in subscribe {
        let slot = push_observer(
            &dep,
            Observer::Consumer {
                node: Rc::downgrade(reader),
                link: position,
            },
        );
        if let Some(link) = consumer.deps.borrow().get(position as usize) {
            link.slot.set(slot);
        }
    }
    // Dropping a link can free its dependency, which can run Python code.
    drop(dropped);
}

/// Unsubscribe from every dependency and forget them.
pub(crate) fn detach_all_deps(reader: &Rc<Node>) {
    let Some(consumer) = reader.consumer.as_deref() else {
        return;
    };
    let links = std::mem::take(&mut *consumer.deps.borrow_mut());
    unlink(node_key(reader), &links);
    drop(links);
}

/// The Python objects of a consumer's current dependencies, in the order
/// they were first read.
pub(crate) fn dependency_handles<'py>(
    py: Python<'py>,
    node: &Node,
) -> PyResult<Bound<'py, PyTuple>> {
    let handles: Vec<Py<PyAny>> = node
        .consumer()
        .deps
        .borrow()
        .iter()
        .map(|link| link.handle.clone_ref(py))
        .collect();
    PyTuple::new(py, handles)
}

// ---------------------------------------------------------------------------
// Invalidation (push)
// ---------------------------------------------------------------------------

/// Mark stale and return whether observers still need to hear about it.
/// `force` upgrades to `MustRefresh`, bypassing the dependency check.
pub(crate) fn invalidate(node: &Node, force: bool) -> bool {
    let consumer = node.consumer();
    let target = if force {
        State::MustRefresh
    } else {
        State::Stale
    };
    if consumer.state.get() < target {
        consumer.state.set(target);
    }
    if consumer.notified.get() {
        return false;
    }
    consumer.notified.set(true);
    true
}

/// Tell `start`'s observers it changed: mark dependent computeds stale,
/// depth-first, and queue dependent effects and `subscribe()` observers.
/// No Python code runs during the walk. Queued work runs once the outermost
/// walk ends, unless a batch or flush is in progress.
pub(crate) fn notify(py: Python<'_>, start: &Rc<Node>) -> PyResult<()> {
    if !has_observers(start) {
        return Ok(());
    }
    let rt = rt();
    rt.wave_depth.set(rt.wave_depth.get() + 1);
    walk(py, start);
    let depth = rt.wave_depth.get() - 1;
    rt.wave_depth.set(depth);
    if depth == 0 {
        effects::flush(py)?;
    }
    Ok(())
}

enum Step {
    Done,
    Skip,
    Consumer(Rc<Node>),
    Python(Py<PyWeakrefReference>),
}

/// Depth-first, with an explicit stack so long chains cannot overflow.
fn walk(py: Python<'_>, start: &Rc<Node>) {
    let mut stack: Vec<(Rc<Node>, usize)> = vec![(start.clone(), 0)];
    while let Some((node, index)) = stack.last_mut() {
        let step = match node.observers.borrow().get(*index) {
            None => Step::Done,
            Some(Observer::Vacant) => Step::Skip,
            Some(Observer::Consumer { node, .. }) => {
                node.upgrade().map_or(Step::Skip, Step::Consumer)
            }
            Some(Observer::Python { reference, .. }) => Step::Python(reference.clone_ref(py)),
        };
        *index += 1;
        match step {
            Step::Done => {
                stack.pop();
            }
            Step::Skip => {}
            Step::Consumer(consumer) => match consumer.kind {
                Kind::Effect => effects::enqueue_effect(&consumer),
                Kind::Computed | Kind::Signal => {
                    if invalidate(&consumer, false) && has_observers(&consumer) {
                        stack.push((consumer, 0));
                    }
                }
            },
            Step::Python(reference) => effects::enqueue_observer(reference),
        }
    }
}

// ---------------------------------------------------------------------------
// Refresh (pull)
// ---------------------------------------------------------------------------

pub(crate) fn ensure_uptodate(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let consumer = node.consumer();
    if consumer.state.get() == State::Fresh {
        return Ok(());
    }
    let _guard = RecursionGuard::enter(py)?;
    // Any refresh attempt means observers must be told about the next change.
    consumer.notified.set(false);
    let state = consumer.state.get();
    // The graph has not changed since this node was last current.
    if state == State::Stale && consumer.clock_seen.get() == clock() {
        consumer.state.set(State::Fresh);
        return Ok(());
    }
    if state == State::Stale && !dependencies_changed(py, node)? {
        consumer.state.set(State::Fresh);
        consumer.clock_seen.set(clock());
        return Ok(());
    }
    refresh(py, node, handle)
}

/// Bring computed dependencies up to date, then report whether any
/// dependency's version differs from the one this consumer last saw.
pub(crate) fn dependencies_changed(py: Python<'_>, node: &Rc<Node>) -> PyResult<bool> {
    let deps = &node.consumer().deps;
    let mut position = 0;
    loop {
        // Signals are compared in place; a computed may run Python code to
        // refresh, so it is copied out first.
        let computed = {
            let deps = deps.borrow();
            let Some(link) = deps.get(position) else {
                return Ok(false);
            };
            if link.node.kind != Kind::Computed {
                if link.version != link.node.version.get() {
                    return Ok(true);
                }
                position += 1;
                continue;
            }
            (link.node.clone(), link.handle.clone_ref(py), link.version)
        };
        let (dep, handle, seen_version) = computed;
        ensure_uptodate(py, &dep, handle.bind(py))?;
        if seen_version != dep.version.get() {
            return Ok(true);
        }
        position += 1;
    }
}

/// Effects only: a dependency changed after this run read it.
pub(crate) fn invalidated_since_read(node: &Node) -> bool {
    node.consumer().deps.borrow().iter().any(|link| {
        link.version != link.node.version.get()
            || (link.node.kind == Kind::Computed && link.node.consumer().notified.get())
    })
}

fn refresh(py: Python<'_>, node: &Rc<Node>, handle: &Bound<'_, PyAny>) -> PyResult<()> {
    let consumer = node.consumer();
    let restore_point = consumer.restore.take();
    if consumer.computing.get() {
        return Err(PyRuntimeError::new_err(
            "Cycle detected while evaluating Computed",
        ));
    }
    let forced = consumer.state.get() == State::MustRefresh;
    let had_outcome = consumer.state.get() != State::Uninitialized;
    let had_error = consumer.error.borrow().is_some();
    let compute = consumer
        .compute
        .borrow()
        .as_ref()
        .map(|compute| compute.clone_ref(py));
    let Some(compute) = compute else {
        return Err(PyRuntimeError::new_err(
            "Computed has no function: it was cleared by the garbage collector or never initialized",
        ));
    };

    // 1) Evaluate with dependency tracking enabled.
    consumer.computing.set(true);
    start_refresh(node);
    push_frame(Some(node.clone()));
    let mut result = run_compute(py, &compute);
    if let Ok(value) = &result {
        if let Err(error) = config::warn_computed_result(py, handle, value.bind(py)) {
            result = Err(error);
        }
    }
    pop_frame();
    consumer.computing.set(false);
    // 2) Subscribe to what this run read, even if it raised.
    commit_refresh(node);
    drop(compute);

    let (mut next_value, mut next_error) = match result {
        Ok(value) => (Some(value), None),
        Err(error) if error.is_instance_of::<PyException>(py) => (None, Some(error)),
        Err(error) => return Err(escalate(consumer, error)),
    };

    // 3) A custom equality can declare a new value unchanged, which keeps the
    // previous object. Its reads are untracked and its errors are cached.
    let previous = node
        .value
        .borrow()
        .as_ref()
        .map(|value| value.clone_ref(py));
    if had_outcome && !had_error {
        let equal = node
            .equal
            .borrow()
            .as_ref()
            .map(|equal| equal.clone_ref(py));
        if let (Some(equal), Some(previous), Some(next)) = (&equal, &previous, &next_value) {
            if !previous.is(next) {
                match call_equal(equal.bind(py), previous.bind(py), next.bind(py)) {
                    Ok(true) => next_value = Some(previous.clone_ref(py)),
                    Ok(false) => {}
                    Err(error) if error.is_instance_of::<PyException>(py) => {
                        next_value = None;
                        next_error = Some(error);
                    }
                    Err(error) => return Err(escalate(consumer, error)),
                }
            }
        }
    }

    // 4) Cache the outcome. Every failed evaluation is a new outcome, and
    // recovery is a change even if the value equals the last successful one.
    let changed = if !had_outcome || had_error || next_error.is_some() {
        true
    } else {
        match (&previous, &next_value) {
            (Some(previous), Some(next)) => has_changed(previous.bind(py), next.bind(py))?,
            _ => true,
        }
    };
    let cached = next_error.map(|error| CachedError {
        traceback: error
            .traceback(py)
            .map(|traceback| traceback.into_any().unbind()),
        exception: error.into_value(py).into_any(),
    });
    let has_error = cached.is_some();
    let old_error = consumer.error.replace(cached);
    consumer.state.set(State::Fresh);
    let mut old_value = None;
    if changed {
        old_value = node.value.replace(next_value);
        consumer.clock_seen.set(bump_version(node));
    } else if forced {
        consumer.clock_seen.set(bump_version(node));
    } else {
        consumer.clock_seen.set(clock());
    }
    drop((old_value, old_error, previous));
    if changed || forced {
        config::hook(py, intern!(py, "updated"), handle)?;
    }

    // 5) A binding read inside `at()` returns to its pre-context value and
    // version when it resolves to that value from the same, unchanged source.
    if let Some(point) = restore_point {
        if !forced && !has_error {
            restore(py, node, &point)?;
        }
    }
    Ok(())
}

/// A control-flow exception aborts evaluation instead of being cached; the
/// next read must retry even though dependencies were committed.
fn escalate(consumer: &Consumer, error: PyErr) -> PyErr {
    if consumer.state.get() < State::MustRefresh {
        consumer.state.set(State::MustRefresh);
    }
    error
}

fn restore(py: Python<'_>, node: &Node, point: &RestorePoint) -> PyResult<()> {
    let same_source = point
        .holder
        .value
        .borrow()
        .as_ref()
        .is_some_and(|current| current.is(&point.source));
    if !same_source || point.source_node.version.get() != point.source_version {
        return Ok(());
    }
    let current = raw_value(py, node);
    if has_changed(point.value.bind(py), &current)? {
        return Ok(());
    }
    let old = node.value.replace(Some(point.value.clone_ref(py)));
    node.version.set(point.version);
    drop(old);
    Ok(())
}

pub(crate) fn run_compute(py: Python<'_>, compute: &Compute) -> PyResult<Py<PyAny>> {
    match compute {
        Compute::Function(f) => Ok(f.bind(py).call0()?.unbind()),
        Compute::Call { func, args } => {
            let func = func.bind(py);
            match args.as_slice() {
                [arg] => Ok(func.call1((resolve_arg(py, arg.bind(py))?,))?.unbind()),
                [left, right] => Ok(func
                    .call1((
                        resolve_arg(py, left.bind(py))?,
                        resolve_arg(py, right.bind(py))?,
                    ))?
                    .unbind()),
                _ => {
                    let mut resolved = Vec::with_capacity(args.len());
                    for arg in args {
                        resolved.push(resolve_arg(py, arg.bind(py))?);
                    }
                    Ok(func.call1(PyTuple::new(py, resolved)?)?.unbind())
                }
            }
        }
        Compute::Source(holder) => {
            let source = resolve_arg(py, holder.bind(py))?;
            Ok(resolve_arg(py, &source)?.unbind())
        }
    }
}

/// Call a custom equality with reads untracked, so it cannot add dependencies.
pub(crate) fn call_equal(
    equal: &Bound<'_, PyAny>,
    previous: &Bound<'_, PyAny>,
    current: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    push_frame(None);
    let result = equal.call1((previous, current));
    pop_frame();
    result?.is_truthy()
}

/// Unwrap one reactive boundary, like `unref`. Instances of the registered
/// classes are read natively; any other reactive object (for example a
/// subclass that overrides `value`) goes through its Python `value` attribute.
pub(crate) fn resolve_arg<'py>(
    py: Python<'py>,
    arg: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    if arg.is_none()
        || arg.is_exact_instance_of::<PyFloat>()
        || arg.is_exact_instance_of::<PyInt>()
        || arg.is_exact_instance_of::<PyString>()
        || arg.is_exact_instance_of::<PyBool>()
    {
        return Ok(arg.clone());
    }
    let arg_type = arg.get_type();
    if is_standard_type(arg_type.as_any()) {
        if let Ok(signal) = arg.cast::<SignalCore>() {
            return read_signal(py, &signal.get().node, arg);
        }
        if let Ok(computed) = arg.cast::<ComputedCore>() {
            return read_computed(py, &computed.get().node, arg);
        }
    }
    let is_reactive = match arg_type.getattr(intern!(py, "_IS_REACTIVE")) {
        Ok(flag) => flag.is_truthy()?,
        Err(_) => false,
    };
    if is_reactive {
        return arg.getattr(intern!(py, "value"));
    }
    Ok(arg.clone())
}

/// Whether `obj` is a Signal, Computed or Binding: an instance of the
/// engine's classes, or of a class marked `_IS_REACTIVE`.
pub(crate) fn is_reactive(obj: &Bound<'_, PyAny>) -> PyResult<bool> {
    if obj.is_instance_of::<SignalCore>() || obj.is_instance_of::<ComputedCore>() {
        return Ok(true);
    }
    match obj.get_type().getattr(intern!(obj.py(), "_IS_REACTIVE")) {
        Ok(flag) => flag.is_truthy(),
        Err(_) => Ok(false),
    }
}

/// Built-in scalars compare by value (NaN equals NaN); everything else by
/// identity. No user equality methods or array comparisons run.
pub(crate) fn has_changed(
    previous: &Bound<'_, PyAny>,
    current: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    if previous.is(current) {
        return Ok(false);
    }
    if !previous.get_type().is(current.get_type()) {
        return Ok(true);
    }
    if previous.is_exact_instance_of::<PyFloat>() {
        let a: f64 = previous.extract()?;
        let b: f64 = current.extract()?;
        return Ok(a != b && !(a.is_nan() && b.is_nan()));
    }
    if previous.is_none()
        || previous.is_exact_instance_of::<PyInt>()
        || previous.is_exact_instance_of::<PyBool>()
        || previous.is_exact_instance_of::<PyString>()
        || previous.is_exact_instance_of::<PyBytes>()
        || previous.is_exact_instance_of::<PyComplex>()
    {
        return previous.ne(current);
    }
    Ok(true)
}

// ---------------------------------------------------------------------------
// Reads and writes
// ---------------------------------------------------------------------------

fn uninitialized() -> PyErr {
    PyRuntimeError::new_err("Signal.__init__() was not called")
}

pub(crate) fn read_signal<'py>(
    py: Python<'py>,
    node: &Rc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let value = match node.value.borrow().as_ref() {
        Some(value) => value.bind(py).clone(),
        None => return Err(uninitialized()),
    };
    config::hook(py, intern!(py, "read"), handle)?;
    track_read(node, handle);
    Ok(value)
}

pub(crate) fn read_computed<'py>(
    py: Python<'py>,
    node: &Rc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    config::hook(py, intern!(py, "read"), handle)?;
    let refreshed = ensure_uptodate(py, node, handle);
    // Register the read even when the refresh raises, so the reader retries.
    track_read(node, handle);
    refreshed?;
    let cached = node.consumer().error.borrow().as_ref().map(|cached| {
        (
            cached.exception.clone_ref(py),
            cached.traceback.as_ref().map(|tb| tb.clone_ref(py)),
        )
    });
    if let Some((exception, traceback)) = cached {
        let exception = exception.into_bound(py);
        // Reset the traceback so repeated reads do not accumulate frames.
        exception.setattr(intern!(py, "__traceback__"), traceback)?;
        return Err(PyErr::from_value(exception));
    }
    Ok(raw_value(py, node))
}

pub(crate) fn raw_value<'py>(py: Python<'py>, node: &Node) -> Bound<'py, PyAny> {
    match node.value.borrow().as_ref() {
        Some(value) => value.bind(py).clone(),
        None => py.None().into_bound(py),
    }
}

/// Assign a signal's value; observers hear about it only if it changed.
pub(crate) fn write_signal(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
) -> PyResult<()> {
    config::warn_signal_value(py, handle, &value)?;
    let old = node.value.borrow().as_ref().map(|old| old.clone_ref(py));
    let Some(old) = old else {
        return Err(uninitialized());
    };
    if !has_changed(old.bind(py), &value)? {
        return Ok(());
    }
    let equal = node
        .equal
        .borrow()
        .as_ref()
        .map(|equal| equal.clone_ref(py));
    if let Some(equal) = equal {
        if call_equal(equal.bind(py), old.bind(py), &value)? {
            return Ok(());
        }
    }
    let previous = node.value.replace(Some(value.unbind()));
    bump_version(node);
    drop(previous);
    drop(old);
    config::hook(py, intern!(py, "updated"), handle)?;
    notify(py, node)
}

/// Notify a signal's observers unconditionally (after an in-place mutation).
pub(crate) fn update_signal(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    bump_version(node);
    config::hook(py, intern!(py, "updated"), handle)?;
    notify(py, node)
}

/// Return a signal to an earlier value and version (the end of `Signal.at`).
/// The clock still advances, so a consumer that refreshed in the meantime
/// cannot take the unchanged-graph fast path.
pub(crate) fn restore_signal(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
    version: u64,
) -> PyResult<()> {
    let previous = node.value.replace(Some(value.unbind()));
    node.version.set(version);
    bump_clock();
    drop(previous);
    config::hook(py, intern!(py, "updated"), handle)?;
    notify(py, node)
}

/// The engine node behind a Signal, Computed or Binding.
pub(crate) fn node_of(obj: &Bound<'_, PyAny>) -> PyResult<Rc<Node>> {
    if let Ok(signal) = obj.cast::<SignalCore>() {
        return Ok(signal.get().node.0.clone());
    }
    if let Ok(computed) = obj.cast::<ComputedCore>() {
        return Ok(computed.get().node.0.clone());
    }
    Err(PyTypeError::new_err(format!(
        "expected a Signal, Computed or Binding, got {}",
        obj.get_type().name()?
    )))
}

// ---------------------------------------------------------------------------
// Python observers
// ---------------------------------------------------------------------------

/// The slot of `observer` in `node`'s observer list, if subscribed.
fn find_python_observer(node: &Node, observer: &Bound<'_, PyAny>) -> Option<u32> {
    let py = observer.py();
    let id = observer.as_ptr() as usize;
    let mut slot = 0;
    loop {
        let candidate = match node.observers.borrow().get(slot) {
            None => return None,
            Some(Observer::Python {
                reference,
                id: other,
            }) if *other == id => Some(reference.clone_ref(py)),
            Some(_) => None,
        };
        if let Some(reference) = candidate {
            if reference
                .bind(py)
                .upgrade()
                .is_some_and(|target| target.is(observer))
            {
                return Some(slot as u32);
            }
        }
        slot += 1;
    }
}

pub(crate) fn add_python_observer(node: &Node, observer: &Bound<'_, PyAny>) -> PyResult<()> {
    if find_python_observer(node, observer).is_some() {
        return Ok(());
    }
    let reference = PyWeakrefReference::new(observer)?.unbind();
    let id = observer.as_ptr() as usize;
    push_observer(node, Observer::Python { reference, id });
    Ok(())
}

pub(crate) fn remove_python_observer(node: &Node, observer: &Bound<'_, PyAny>) {
    if let Some(slot) = find_python_observer(node, observer) {
        drop(vacate(node, slot));
    }
}

/// Live observers of `node`; dead `subscribe()` observers are removed.
pub(crate) fn live_observer_count(py: Python<'_>, node: &Node) -> usize {
    let mut count = 0;
    let mut dead = Vec::new();
    let mut slot = 0;
    loop {
        let alive = match node.observers.borrow().get(slot) {
            None => break,
            Some(Observer::Vacant) => None,
            Some(Observer::Consumer { node, .. }) => Some(node.strong_count() > 0),
            Some(Observer::Python { reference, .. }) => {
                Some(reference.bind(py).upgrade().is_some())
            }
        };
        match alive {
            Some(true) => count += 1,
            Some(false) => dead.push(slot as u32),
            None => {}
        }
        slot += 1;
    }
    let removed: Vec<Observer> = dead.into_iter().map(|slot| take_slot(node, slot)).collect();
    compact_if_sparse(node);
    drop(removed);
    count
}
