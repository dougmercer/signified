//! Graph state and the propagation algorithm: dependency tracking, push
//! invalidation and pull refresh, ported from the Python engine that
//! signified 0.6 shipped with.

use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::{Arc, OnceLock, Weak};

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
use crate::effects;

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

/// Above this many dependencies, a node indexes its links by dependency.
const INDEX_THRESHOLD: usize = 16;

/// A subscriber of a node. Engine nodes are held weakly in Rust; Python
/// observers added with `subscribe()`, and computeds whose class overrides
/// `update`, are held through Python weakrefs.
pub(crate) enum Observer {
    Node(Weak<Node>),
    Python(Py<PyWeakrefReference>),
}

impl Observer {
    fn clone_ref(&self, py: Python<'_>) -> Observer {
        match self {
            Observer::Node(weak) => Observer::Node(weak.clone()),
            Observer::Python(reference) => Observer::Python(reference.clone_ref(py)),
        }
    }

    fn is_alive(&self, py: Python<'_>) -> bool {
        match self {
            Observer::Node(weak) => weak.strong_count() > 0,
            Observer::Python(reference) => reference.bind(py).upgrade().is_some(),
        }
    }
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
}

impl Compute {
    pub(crate) fn clone_ref(&self, py: Python<'_>) -> Compute {
        match self {
            Compute::Function(f) => Compute::Function(f.clone_ref(py)),
            Compute::Call { func, args } => Compute::Call {
                func: func.clone_ref(py),
                args: args.iter().map(|arg| arg.clone_ref(py)).collect(),
            },
        }
    }
}

/// Edge from a consumer to one dependency, reused across refreshes.
pub(crate) struct DepLink {
    pub(crate) node: Arc<Node>,
    /// The dependency's Python object; keeps it alive and is visible to the GC.
    pub(crate) handle: Py<PyAny>,
    version: u64,
    read_version: u64,
    seen: u64,
    active: bool,
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
    pub(crate) holder: Arc<Node>,
    pub(crate) source: Py<PyAny>,
    pub(crate) source_node: Arc<Node>,
    pub(crate) source_version: u64,
}

pub(crate) struct Node {
    pub(crate) kind: Kind,
    pub(crate) value: RefCell<Option<Py<PyAny>>>,
    pub(crate) version: Cell<u64>,
    pub(crate) observers: RefCell<Vec<Observer>>,
    pub(crate) compute: RefCell<Option<Compute>>,
    pub(crate) equal: RefCell<Option<Py<PyAny>>>,
    pub(crate) name: RefCell<Option<Py<PyAny>>>,
    pub(crate) state: Cell<State>,
    computing: Cell<bool>,
    pub(crate) notified: Cell<bool>,
    clock_seen: Cell<u64>,
    token: Cell<u64>,
    pub(crate) deps: RefCell<Vec<DepLink>>,
    dep_cursor: Cell<usize>,
    dep_index: RefCell<Option<HashMap<usize, usize>>>,
    pub(crate) error: RefCell<Option<CachedError>>,
    pub(crate) restore: RefCell<Option<RestorePoint>>,
    /// The node's class overrides `update` (or, for a computed, `notify`):
    /// the engine calls it, and a consumer subscribes as a Python observer.
    pub(crate) python_update: Cell<bool>,
    /// The node's class overrides `notify`, so the engine calls it.
    pub(crate) python_notify: Cell<bool>,
    /// A weak reference to the node's Python object, kept only when its class
    /// overrides `update` or `notify`.
    pub(crate) owner: RefCell<Option<Py<PyWeakrefReference>>>,
    /// Effects only: not disposed.
    pub(crate) active: Cell<bool>,
    /// Effects only: has run at least once.
    pub(crate) has_run: Cell<bool>,
}

// SAFETY: every field is read and written only by code running while attached
// to the interpreter, and the GIL lets one thread run at a time (the module is
// `gil_used = true`). No borrow is held across a call into Python, so a thread
// switch inside such a call never observes a cell mid-update. Concurrent use
// from several threads is unsupported, but it cannot cause a data race.
unsafe impl Send for Node {}
unsafe impl Sync for Node {}

impl Node {
    pub(crate) fn new(kind: Kind) -> Node {
        Node {
            kind,
            value: RefCell::new(None),
            version: Cell::new(0),
            observers: RefCell::new(Vec::new()),
            compute: RefCell::new(None),
            equal: RefCell::new(None),
            name: RefCell::new(None),
            state: Cell::new(match kind {
                Kind::Computed => State::Uninitialized,
                Kind::Signal | Kind::Effect => State::Fresh,
            }),
            computing: Cell::new(false),
            notified: Cell::new(false),
            clock_seen: Cell::new(NEVER),
            token: Cell::new(0),
            deps: RefCell::new(Vec::new()),
            dep_cursor: Cell::new(0),
            dep_index: RefCell::new(None),
            error: RefCell::new(None),
            restore: RefCell::new(None),
            python_update: Cell::new(false),
            python_notify: Cell::new(false),
            owner: RefCell::new(None),
            active: Cell::new(false),
            has_run: Cell::new(false),
        }
    }

    /// Visit every Python object this node owns; busy cells are skipped.
    pub(crate) fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        if let Ok(value) = self.value.try_borrow() {
            if let Some(value) = value.as_ref() {
                visit.call(value)?;
            }
        }
        if let Ok(compute) = self.compute.try_borrow() {
            match compute.as_ref() {
                Some(Compute::Function(f)) => visit.call(f)?,
                Some(Compute::Call { func, args }) => {
                    visit.call(func)?;
                    for arg in args {
                        visit.call(arg)?;
                    }
                }
                None => {}
            }
        }
        if let Ok(equal) = self.equal.try_borrow() {
            if let Some(equal) = equal.as_ref() {
                visit.call(equal)?;
            }
        }
        if let Ok(error) = self.error.try_borrow() {
            if let Some(cached) = error.as_ref() {
                visit.call(&cached.exception)?;
                if let Some(traceback) = cached.traceback.as_ref() {
                    visit.call(traceback)?;
                }
            }
        }
        if let Ok(deps) = self.deps.try_borrow() {
            for link in deps.iter() {
                visit.call(&link.handle)?;
            }
        }
        if let Ok(restore) = self.restore.try_borrow() {
            if let Some(point) = restore.as_ref() {
                visit.call(&point.value)?;
                visit.call(&point.source)?;
            }
        }
        Ok(())
    }

    /// Drop every Python object this node owns (for `__clear__`).
    pub(crate) fn clear(self: &Arc<Self>, py: Python<'_>) {
        detach_all_deps(py, self, None);
        let compute = self.compute.take();
        let value = self.value.take();
        let equal = self.equal.take();
        let name = self.name.take();
        let error = self.error.take();
        let restore = self.restore.take();
        let owner = self.owner.take();
        drop((compute, value, equal, name, error, restore, owner));
    }
}

// ---------------------------------------------------------------------------
// Runtime: version clock, tracking frames, notification wave, effect queue
// ---------------------------------------------------------------------------

pub(crate) struct Runtime {
    clock: Cell<u64>,
    /// The consumer being evaluated, innermost last; `None` marks an untracked block.
    frames: RefCell<Vec<Option<Arc<Node>>>>,
    /// Nodes already notified in the current wave.
    wave: RefCell<HashSet<usize>>,
    pub(crate) wave_depth: Cell<u32>,
    /// Classes whose `.value` is the engine's own getter (see `resolve_arg`).
    standard_types: RefCell<Vec<Py<PyAny>>>,
    /// Effects waiting to run, in scheduling order, with a sequence number.
    pub(crate) pending: RefCell<VecDeque<(Weak<Node>, u64)>>,
    /// The live sequence number of each pending effect.
    pub(crate) pending_index: RefCell<HashMap<usize, u64>>,
    pub(crate) pending_seq: Cell<u64>,
    pub(crate) batch_depth: Cell<u32>,
    pub(crate) flushing: Cell<bool>,
    /// The plugin manager's `hook` object, when hooks are on.
    pub(crate) hooks: RefCell<Option<Py<PyAny>>>,
    pub(crate) hooks_on: Cell<bool>,
    pub(crate) migration_warnings: Cell<bool>,
}

// SAFETY: as for `Node`; one runtime is shared by all threads, like the
// module-level state of a Python implementation, and the GIL serializes access.
unsafe impl Send for Runtime {}
unsafe impl Sync for Runtime {}

pub(crate) fn rt() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(|| Runtime {
        clock: Cell::new(0),
        frames: RefCell::new(Vec::new()),
        wave: RefCell::new(HashSet::new()),
        wave_depth: Cell::new(0),
        standard_types: RefCell::new(Vec::new()),
        pending: RefCell::new(VecDeque::new()),
        pending_index: RefCell::new(HashMap::new()),
        pending_seq: Cell::new(0),
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

pub(crate) fn push_frame(frame: Option<Arc<Node>>) {
    rt().frames.borrow_mut().push(frame);
}

pub(crate) fn pop_frame() -> Option<Option<Arc<Node>>> {
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
// Dependency tracking
// ---------------------------------------------------------------------------

fn node_key(node: &Node) -> usize {
    node as *const Node as usize
}

fn track_read(node: &Arc<Node>, handle: &Bound<'_, PyAny>) {
    let frames = rt().frames.borrow();
    if let Some(Some(reader)) = frames.last() {
        // Self-reads would make a node depend on itself.
        if !Arc::ptr_eq(reader, node) {
            register_dependency(reader, node, handle);
        }
    }
}

/// Stamp `dep`'s link with the current refresh, adding the link if needed.
/// Only Rust allocations happen here, so holding borrows is safe.
fn register_dependency(reader: &Node, dep: &Arc<Node>, handle: &Bound<'_, PyAny>) {
    let token = reader.token.get();
    let read_version = dep.version.get();
    let mut deps = reader.deps.borrow_mut();
    // Reads usually repeat the previous refresh's order, so try the next link first.
    let cursor = reader.dep_cursor.get();
    let position = if deps
        .get(cursor)
        .is_some_and(|link| Arc::ptr_eq(&link.node, dep))
    {
        Some(cursor)
    } else {
        match reader.dep_index.borrow().as_ref() {
            Some(index) => index.get(&node_key(dep)).copied(),
            None => deps.iter().position(|link| Arc::ptr_eq(&link.node, dep)),
        }
    };
    match position {
        Some(position) => {
            let link = &mut deps[position];
            link.seen = token;
            link.read_version = read_version;
            reader.dep_cursor.set(position + 1);
        }
        None => {
            let position = deps.len();
            deps.push(DepLink {
                node: dep.clone(),
                handle: handle.clone().unbind(),
                version: NEVER,
                read_version,
                seen: token,
                active: false,
            });
            reader.dep_cursor.set(position + 1);
            let mut index = reader.dep_index.borrow_mut();
            match index.as_mut() {
                Some(index) => {
                    index.insert(node_key(dep), position);
                }
                None if deps.len() > INDEX_THRESHOLD => *index = Some(build_index(&deps)),
                None => {}
            }
        }
    }
}

fn build_index(deps: &[DepLink]) -> HashMap<usize, usize> {
    deps.iter()
        .enumerate()
        .map(|(position, link)| (node_key(&link.node), position))
        .collect()
}

pub(crate) fn start_refresh(node: &Node) {
    node.token.set(node.token.get() + 1);
    node.dep_cursor.set(0);
}

/// Subscribe to every dependency read during this run and drop the rest. Runs
/// after successful and failed runs alike, so a consumer always depends on
/// exactly what its last run read.
pub(crate) fn commit_refresh(
    py: Python<'_>,
    reader: &Arc<Node>,
    handle: Option<&Bound<'_, PyAny>>,
) {
    let token = reader.token.get();
    let owner = owner_of(py, reader, handle);
    let python_update = owner.is_some();
    let mut dropped = Vec::new();
    let mut subscribe = Vec::new();
    let mut unsubscribe = Vec::new();
    {
        let mut deps = reader.deps.borrow_mut();
        let mut kept = Vec::with_capacity(deps.len());
        for mut link in deps.drain(..) {
            if link.seen == token {
                if !link.active {
                    if python_update {
                        subscribe.push(link.node.clone());
                    } else {
                        link.node
                            .observers
                            .borrow_mut()
                            .push(Observer::Node(Arc::downgrade(reader)));
                    }
                    link.active = true;
                }
                link.version = link.read_version;
                kept.push(link);
            } else {
                if link.active {
                    if python_update {
                        unsubscribe.push(link.node.clone());
                    } else {
                        remove_node_observer(&link.node, reader);
                    }
                }
                dropped.push(link);
            }
        }
        let changed = !dropped.is_empty();
        *deps = kept;
        let mut index = reader.dep_index.borrow_mut();
        if deps.len() > INDEX_THRESHOLD {
            if changed || index.is_none() {
                *index = Some(build_index(&deps));
            }
        } else {
            *index = None;
        }
    }
    if let Some(owner) = &owner {
        for dep in subscribe {
            // Errors here mean the reader cannot be weakly referenced, which
            // `__init__` already ruled out.
            let _ = add_python_observer(&dep, owner);
        }
        for dep in unsubscribe {
            remove_python_observer(py, &dep, owner);
        }
    }
    // Dropping a link can free its dependency, which can run Python code.
    drop(dropped);
}

fn remove_node_observer(dep: &Node, reader: &Arc<Node>) {
    let target = Arc::as_ptr(reader);
    dep.observers
        .borrow_mut()
        .retain(|observer| match observer {
            Observer::Node(weak) => weak.as_ptr() != target && weak.strong_count() > 0,
            Observer::Python(_) => true,
        });
}

/// The Python object of a consumer that subscribes through Python, if any.
fn owner_of<'py>(
    py: Python<'py>,
    node: &Node,
    handle: Option<&Bound<'py, PyAny>>,
) -> Option<Bound<'py, PyAny>> {
    if !node.python_update.get() {
        return None;
    }
    if let Some(handle) = handle {
        return Some(handle.clone());
    }
    let reference = node
        .owner
        .borrow()
        .as_ref()
        .map(|reference| reference.clone_ref(py));
    reference.and_then(|reference| reference.bind(py).upgrade())
}

/// Unsubscribe from every dependency and forget them.
pub(crate) fn detach_all_deps(
    py: Python<'_>,
    reader: &Arc<Node>,
    handle: Option<&Bound<'_, PyAny>>,
) {
    let links = std::mem::take(&mut *reader.deps.borrow_mut());
    reader.dep_index.replace(None);
    let owner = owner_of(py, reader, handle);
    for link in &links {
        if link.active {
            match &owner {
                Some(owner) => remove_python_observer(py, &link.node, owner),
                None => remove_node_observer(&link.node, reader),
            }
        }
    }
    drop(links);
}

/// The Python objects of a consumer's current dependencies, in the order
/// they were first read.
pub(crate) fn dependency_handles<'py>(
    py: Python<'py>,
    node: &Node,
) -> PyResult<Bound<'py, PyTuple>> {
    let handles: Vec<Py<PyAny>> = node
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
    let target = if force {
        State::MustRefresh
    } else {
        State::Stale
    };
    if node.state.get() < target {
        node.state.set(target);
    }
    if node.notified.get() {
        return false;
    }
    node.notified.set(true);
    true
}

/// Prune dead observers and return a snapshot that is safe to iterate while
/// Python code runs.
fn snapshot_observers(py: Python<'_>, node: &Node) -> Vec<Observer> {
    let current = std::mem::take(&mut *node.observers.borrow_mut());
    let (alive, dead): (Vec<Observer>, Vec<Observer>) = current
        .into_iter()
        .partition(|observer| observer.is_alive(py));
    let snapshot = alive
        .iter()
        .map(|observer| observer.clone_ref(py))
        .collect();
    {
        let mut observers = node.observers.borrow_mut();
        // Keep anything subscribed while the list was taken out.
        let added = std::mem::take(&mut *observers);
        *observers = alive;
        observers.extend(added);
    }
    drop(dead);
    snapshot
}

fn mark_notified(node: &Node) -> bool {
    rt().wave.borrow_mut().insert(node_key(node))
}

/// Tell `start`'s observers it changed: invalidate dependent computeds
/// depth-first, schedule dependent effects, call Python observers' `update()`.
/// A node without observers stays out of the wave, so observers added later in
/// the wave still hear its next write. Effects run once the outermost wave ends.
/// Notify `node`'s observers through its class's `notify` if it overrides it.
pub(crate) fn notify_node(
    py: Python<'_>,
    node: &Arc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    if node.python_notify.get() {
        handle.call_method0(intern!(py, "notify"))?;
        return Ok(());
    }
    notify(py, node)
}

pub(crate) fn notify(py: Python<'_>, start: &Arc<Node>) -> PyResult<()> {
    let observers = snapshot_observers(py, start);
    if observers.is_empty() || !mark_notified(start) {
        return Ok(());
    }
    let rt = rt();
    rt.wave_depth.set(rt.wave_depth.get() + 1);
    let result = notify_wave(py, observers);
    let depth = rt.wave_depth.get() - 1;
    rt.wave_depth.set(depth);
    if depth == 0 {
        rt.wave.borrow_mut().clear();
    }
    result?;
    if depth == 0 {
        effects::flush(py)?;
    }
    Ok(())
}

/// Walk observers depth-first with an explicit stack, so long chains cannot
/// overflow.
fn notify_wave(py: Python<'_>, first: Vec<Observer>) -> PyResult<()> {
    let mut frames: Vec<(Vec<Observer>, usize)> = vec![(first, 0)];
    while let Some((observers, index)) = frames.last_mut() {
        if *index >= observers.len() {
            frames.pop();
            continue;
        }
        let observer = observers[*index].clone_ref(py);
        *index += 1;
        match observer {
            Observer::Node(weak) => {
                let Some(node) = weak.upgrade() else {
                    continue;
                };
                match node.kind {
                    Kind::Effect => effects::schedule(py, &node)?,
                    Kind::Computed | Kind::Signal => {
                        if invalidate(&node, false) {
                            let next = snapshot_observers(py, &node);
                            if !next.is_empty() && mark_notified(&node) {
                                frames.push((next, 0));
                            }
                        }
                    }
                }
            }
            Observer::Python(reference) => {
                let target = reference.bind(py).upgrade();
                if let Some(target) = target {
                    target.call_method0(intern!(py, "update"))?;
                }
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Refresh (pull)
// ---------------------------------------------------------------------------

pub(crate) fn ensure_uptodate(
    py: Python<'_>,
    node: &Arc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    if node.state.get() == State::Fresh {
        return Ok(());
    }
    let _guard = RecursionGuard::enter(py)?;
    // Any refresh attempt means observers must be told about the next change.
    node.notified.set(false);
    let state = node.state.get();
    // The graph has not changed since this node was last current.
    if state == State::Stale && node.clock_seen.get() == clock() {
        node.state.set(State::Fresh);
        return Ok(());
    }
    if state == State::Stale && !dependencies_changed(py, node)? {
        node.state.set(State::Fresh);
        node.clock_seen.set(clock());
        return Ok(());
    }
    refresh(py, node, handle)
}

/// Bring computed dependencies up to date, then report whether any
/// dependency's version differs from the one this consumer last saw.
pub(crate) fn dependencies_changed(py: Python<'_>, node: &Arc<Node>) -> PyResult<bool> {
    let mut position = 0;
    loop {
        let next = node
            .deps
            .borrow()
            .get(position)
            .map(|link| (link.node.clone(), link.handle.clone_ref(py), link.version));
        let Some((dep, handle, seen_version)) = next else {
            return Ok(false);
        };
        if dep.kind == Kind::Computed {
            ensure_uptodate(py, &dep, handle.bind(py))?;
        }
        if seen_version != dep.version.get() {
            return Ok(true);
        }
        position += 1;
    }
}

/// Effects only: a dependency changed after this run read it.
pub(crate) fn invalidated_since_read(node: &Node) -> bool {
    node.deps.borrow().iter().any(|link| {
        link.version != link.node.version.get()
            || (link.node.kind == Kind::Computed && link.node.notified.get())
    })
}

fn refresh(py: Python<'_>, node: &Arc<Node>, handle: &Bound<'_, PyAny>) -> PyResult<()> {
    let restore_point = node.restore.take();
    if node.computing.get() {
        return Err(PyRuntimeError::new_err(
            "Cycle detected while evaluating Computed",
        ));
    }
    let forced = node.state.get() == State::MustRefresh;
    let had_outcome = node.state.get() != State::Uninitialized;
    let had_error = node.error.borrow().is_some();
    let compute = node
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
    node.computing.set(true);
    start_refresh(node);
    push_frame(Some(node.clone()));
    let mut result = run_compute(py, &compute);
    if let Ok(value) = &result {
        if let Err(error) = config::warn_computed_result(py, handle, value.bind(py)) {
            result = Err(error);
        }
    }
    pop_frame();
    node.computing.set(false);
    // 2) Subscribe to what this run read, even if it raised.
    commit_refresh(py, node, Some(handle));
    drop(compute);

    let (mut next_value, mut next_error) = match result {
        Ok(value) => (Some(value), None),
        Err(error) if error.is_instance_of::<PyException>(py) => (None, Some(error)),
        Err(error) => return Err(escalate(node, error)),
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
                match call_equal(py, equal.bind(py), previous.bind(py), next.bind(py)) {
                    Ok(true) => next_value = Some(previous.clone_ref(py)),
                    Ok(false) => {}
                    Err(error) if error.is_instance_of::<PyException>(py) => {
                        next_value = None;
                        next_error = Some(error);
                    }
                    Err(error) => return Err(escalate(node, error)),
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
    let old_error = node.error.replace(cached);
    node.state.set(State::Fresh);
    let mut old_value = None;
    if changed {
        old_value = node.value.replace(next_value);
        node.clock_seen.set(bump_version(node));
    } else if forced {
        node.clock_seen.set(bump_version(node));
    } else {
        node.clock_seen.set(clock());
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
fn escalate(node: &Node, error: PyErr) -> PyErr {
    if node.state.get() < State::MustRefresh {
        node.state.set(State::MustRefresh);
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
    }
}

/// Call a custom equality with reads untracked, so it cannot add dependencies.
pub(crate) fn call_equal(
    py: Python<'_>,
    equal: &Bound<'_, PyAny>,
    previous: &Bound<'_, PyAny>,
    current: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let _ = py;
    push_frame(None);
    let result = equal.call1((previous, current));
    pop_frame();
    result?.is_truthy()
}

/// Unwrap one reactive boundary, like `unref`. Instances of the registered
/// classes are read natively; any other reactive object (for example a
/// subclass that overrides `value`) goes through its Python `value` attribute.
fn resolve_arg<'py>(py: Python<'py>, arg: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
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

pub(crate) fn read_signal<'py>(
    py: Python<'py>,
    node: &Arc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    config::hook(py, intern!(py, "read"), handle)?;
    track_read(node, handle);
    Ok(raw_value(py, node))
}

pub(crate) fn read_computed<'py>(
    py: Python<'py>,
    node: &Arc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    config::hook(py, intern!(py, "read"), handle)?;
    let refreshed = ensure_uptodate(py, node, handle);
    // Register the read even when the refresh raises, so the reader retries.
    track_read(node, handle);
    refreshed?;
    let cached = node.error.borrow().as_ref().map(|cached| {
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
    node: &Arc<Node>,
    handle: &Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
) -> PyResult<()> {
    config::warn_signal_value(py, handle, &value)?;
    let old = node.value.borrow().as_ref().map(|old| old.clone_ref(py));
    if let Some(old) = &old {
        if !has_changed(old.bind(py), &value)? {
            return Ok(());
        }
        let equal = node
            .equal
            .borrow()
            .as_ref()
            .map(|equal| equal.clone_ref(py));
        if let Some(equal) = equal {
            if call_equal(py, equal.bind(py), old.bind(py), &value)? {
                return Ok(());
            }
        }
    }
    let previous = node.value.replace(Some(value.unbind()));
    bump_version(node);
    drop(previous);
    drop(old);
    config::hook(py, intern!(py, "updated"), handle)?;
    notify_node(py, node, handle)
}

/// Notify a signal's observers unconditionally (after an in-place mutation).
pub(crate) fn update_signal(
    py: Python<'_>,
    node: &Arc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    bump_version(node);
    config::hook(py, intern!(py, "updated"), handle)?;
    notify_node(py, node, handle)
}

/// Return a signal to an earlier value and version (the end of `Signal.at`).
/// The clock still advances, so a consumer that refreshed in the meantime
/// cannot take the unchanged-graph fast path.
pub(crate) fn restore_signal(
    py: Python<'_>,
    node: &Arc<Node>,
    handle: &Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
    version: u64,
) -> PyResult<()> {
    let previous = node.value.replace(Some(value.unbind()));
    node.version.set(version);
    bump_clock();
    drop(previous);
    config::hook(py, intern!(py, "updated"), handle)?;
    notify_node(py, node, handle)
}

/// The engine node behind a Signal, Computed or Binding.
pub(crate) fn node_of(obj: &Bound<'_, PyAny>) -> PyResult<Arc<Node>> {
    if let Ok(signal) = obj.cast::<SignalCore>() {
        return Ok(signal.get().node.clone());
    }
    if let Ok(computed) = obj.cast::<ComputedCore>() {
        return Ok(computed.get().node.clone());
    }
    Err(PyTypeError::new_err(format!(
        "expected a Signal, Computed or Binding, got {}",
        obj.get_type().name()?
    )))
}

// ---------------------------------------------------------------------------
// Python observers
// ---------------------------------------------------------------------------

pub(crate) fn add_python_observer(node: &Node, observer: &Bound<'_, PyAny>) -> PyResult<()> {
    let py = observer.py();
    let existing: Vec<Py<PyWeakrefReference>> = node
        .observers
        .borrow()
        .iter()
        .filter_map(|o| match o {
            Observer::Python(reference) => Some(reference.clone_ref(py)),
            Observer::Node(_) => None,
        })
        .collect();
    for reference in &existing {
        if let Some(target) = reference.bind(py).upgrade() {
            if target.is(observer) {
                return Ok(());
            }
        }
    }
    drop(existing);
    let reference = PyWeakrefReference::new(observer)?.unbind();
    node.observers
        .borrow_mut()
        .push(Observer::Python(reference));
    Ok(())
}

pub(crate) fn remove_python_observer(py: Python<'_>, node: &Node, observer: &Bound<'_, PyAny>) {
    let current = std::mem::take(&mut *node.observers.borrow_mut());
    let (removed, kept): (Vec<Observer>, Vec<Observer>) =
        current.into_iter().partition(|o| match o {
            Observer::Python(reference) => reference
                .bind(py)
                .upgrade()
                .is_some_and(|target| target.is(observer)),
            Observer::Node(_) => false,
        });
    {
        let mut observers = node.observers.borrow_mut();
        let added = std::mem::take(&mut *observers);
        *observers = kept;
        observers.extend(added);
    }
    drop(removed);
}

pub(crate) fn live_observer_count(py: Python<'_>, node: &Node) -> usize {
    snapshot_observers(py, node).len()
}
