//! Dependency tracking: which consumer is running, the reads it makes, and
//! the edges between it and what it read.
//!
//! Edges are stored twice. A consumer (computed or effect) keeps its
//! dependencies in `deps`, in the order it first read them. Each dependency
//! keeps its consumers in `observers`. A dependency link records its slot in
//! the dependency's observer list, and that entry records the link's position,
//! so either side can find the other in constant time. Removed observers leave
//! a vacant slot until the list compacts, which keeps notification order.

use std::cell::Cell;
use std::rc::Rc;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use crate::node::{DepLink, Node, Observer, ReaderLink, NEVER, NO_SLOT};
use crate::runtime::rt;

/// Observer lists at least this long compact once half their slots are vacant.
const COMPACT_MIN_LEN: usize = 16;

// ---------------------------------------------------------------------------
// Tracking frames
// ---------------------------------------------------------------------------

/// Push a tracking frame and return the depth to pass to `end_frame`.
pub(crate) fn push_frame(frame: Option<Rc<Node>>) -> usize {
    let mut frames = rt().frames.borrow_mut();
    frames.push(frame);
    frames.len() - 1
}

fn pop_frame() -> Option<Option<Rc<Node>>> {
    rt().frames.borrow_mut().pop()
}

/// Remove the frame that `push_frame` returned `depth` for. If code inside
/// left an `untracked()` block open, the frames above it are removed too and
/// the run fails, so later reads are not registered with the wrong consumer.
#[inline]
pub(crate) fn end_frame(depth: usize) -> PyResult<()> {
    let mut frames = rt().frames.borrow_mut();
    if frames.len() == depth + 1 {
        let frame = frames.pop();
        drop(frames);
        drop(frame);
        return Ok(());
    }
    drop(frames);
    unbalanced_frames(depth)
}

#[cold]
fn unbalanced_frames(depth: usize) -> PyResult<()> {
    let removed = {
        let mut frames = rt().frames.borrow_mut();
        let keep = depth.min(frames.len());
        frames.split_off(keep)
    };
    // Dropping a frame can free its node.
    drop(removed);
    Err(PyRuntimeError::new_err(
        "tracking frames are unbalanced: an untracked() block was left open inside a computation \
         or effect, or the reactive graph was used from several threads",
    ))
}

/// Whether the innermost frame is an untracked block.
fn in_untracked_block() -> bool {
    matches!(rt().frames.borrow().last(), Some(None))
}

/// Whether a reactive read right now would register a dependency.
#[pyfunction]
pub fn is_tracking() -> bool {
    matches!(rt().frames.borrow().last(), Some(Some(_)))
}

/// `with untracked():` reads inside do not subscribe the enclosing
/// computation or effect.
#[pyclass(frozen, module = "signified._core", name = "Untracked")]
pub struct Untracked;

#[pymethods]
impl Untracked {
    #[new]
    fn new() -> Self {
        Untracked
    }

    fn __enter__(&self) {
        push_frame(None);
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&self, _exc: &Bound<'_, PyTuple>) -> PyResult<bool> {
        // Check before popping, so a mismatch cannot remove a computation's frame.
        if !in_untracked_block() {
            return Err(PyRuntimeError::new_err(
                "untracked() exited without a matching enter",
            ));
        }
        drop(pop_frame());
        Ok(false)
    }
}

// ---------------------------------------------------------------------------
// Recording reads
// ---------------------------------------------------------------------------

pub(crate) fn track_read(node: &Rc<Node>, handle: &Bound<'_, PyAny>) {
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
// Observer lists
// ---------------------------------------------------------------------------

fn node_key(node: &Node) -> usize {
    node as *const Node as usize
}

pub(crate) fn has_observers(node: &Node) -> bool {
    node.observers.borrow().len() > node.vacant.get() as usize
}

pub(crate) fn push_observer(node: &Node, observer: Observer) -> u32 {
    let mut observers = node.observers.borrow_mut();
    observers.push(observer);
    (observers.len() - 1) as u32
}

/// Remove the observer in `slot` without compacting, and return it so the
/// caller drops it with nothing borrowed.
pub(crate) fn take_slot(node: &Node, slot: u32) -> Observer {
    let removed = match node.observers.borrow_mut().get_mut(slot as usize) {
        Some(entry) => std::mem::replace(entry, Observer::Vacant),
        None => Observer::Vacant,
    };
    match &removed {
        Observer::Vacant => return removed,
        Observer::Python { id, .. } => {
            if let Some(subscribers) = node.subscribers.borrow_mut().as_mut() {
                if subscribers.get(id) == Some(&slot) {
                    subscribers.remove(id);
                }
            }
        }
        Observer::Consumer { .. } => {}
    }
    node.vacant.set(node.vacant.get() + 1);
    removed
}

/// Remove the observer in `slot`, compacting the list if it got sparse.
pub(crate) fn vacate(node: &Node, slot: u32) -> Observer {
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

/// Drop vacant slots once they make up half of a long list. Consumers and
/// `subscribe()` observers whose entries move get their slots updated. Not
/// during a notification walk, which iterates the lists by position.
pub(crate) fn compact_if_sparse(node: &Node) {
    let vacant = node.vacant.get() as usize;
    let len = node.observers.borrow().len();
    let all_vacant = vacant == len;
    if rt().wave_depth.get() > 0 || !(all_vacant || (len >= COMPACT_MIN_LEN && vacant * 2 > len)) {
        return;
    }
    let mut observers = node.observers.borrow_mut();
    let mut subscribers = node.subscribers.borrow_mut();
    let mut write = 0;
    for read in 0..observers.len() {
        if matches!(observers[read], Observer::Vacant) {
            continue;
        }
        if read != write {
            observers.swap(read, write);
            match &observers[write] {
                Observer::Consumer {
                    node: consumer,
                    link,
                } => {
                    if let Some(consumer) = consumer.upgrade() {
                        if let Some(link) = consumer.consumer().deps.borrow().get(*link as usize) {
                            link.slot.set(write as u32);
                        }
                    }
                }
                Observer::Python { id, .. } => {
                    if let Some(slot) = subscribers.as_mut().and_then(|map| map.get_mut(id)) {
                        if *slot == read as u32 {
                            *slot = write as u32;
                        }
                    }
                }
                Observer::Vacant => {}
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
pub(crate) fn unlink(key: usize, links: &[DepLink]) {
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
