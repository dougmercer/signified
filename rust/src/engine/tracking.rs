//! Dependency tracking: which consumer is running, the reads it makes, and
//! the edges between it and what it read.
//!
//! Edges are stored twice. A consumer (computed or effect) keeps its
//! dependencies in `deps`, in the order it first read them. Each dependency
//! keeps its consumers in `observers`. A dependency link records its slot in
//! the dependency's observer list, and that entry records the link's position,
//! so either side can find the other in constant time. Removed observers leave
//! a vacant slot until the list compacts, which keeps notification order.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use crate::engine::node::{DepLink, Node, ReaderLink, NEVER, NO_SLOT};
use crate::engine::runtime::with_rt;

// ---------------------------------------------------------------------------
// Tracking frames
// ---------------------------------------------------------------------------

type FrameStack = RefCell<Vec<Option<Rc<Node>>>>;

/// The consumers this thread is evaluating, innermost last; `None` marks an
/// untracked block. Part of the runtime.
pub(crate) struct Frames(FrameStack);

impl Frames {
    pub(crate) const fn new() -> Frames {
        Frames(RefCell::new(Vec::new()))
    }
}

fn with_frames<R>(f: impl FnOnce(&FrameStack) -> R) -> R {
    with_rt(|rt| f(&rt.frames.0))
}

/// Push a tracking frame and return the depth to pass to `end_frame`.
pub(crate) fn push_frame(frame: Option<Rc<Node>>) -> usize {
    with_frames(|frames| {
        let mut frames = frames.borrow_mut();
        frames.push(frame);
        frames.len() - 1
    })
}

pub(crate) fn pop_frame() -> Option<Option<Rc<Node>>> {
    with_frames(|frames| frames.borrow_mut().pop())
}

/// Remove the frame that `push_frame` returned `depth` for. If code inside
/// left an `untracked()` block open, the frames above it are removed too and
/// the run fails, so later reads are not registered with the wrong consumer.
#[inline]
pub(crate) fn end_frame(depth: usize) -> PyResult<()> {
    let popped = with_frames(|frames| {
        let mut frames = frames.borrow_mut();
        (frames.len() == depth + 1).then(|| frames.pop())
    });
    match popped {
        Some(frame) => {
            drop(frame);
            Ok(())
        }
        None => unbalanced_frames(depth),
    }
}

#[cold]
fn unbalanced_frames(depth: usize) -> PyResult<()> {
    let removed = with_frames(|frames| {
        let mut frames = frames.borrow_mut();
        let keep = depth.min(frames.len());
        frames.split_off(keep)
    });
    // Dropping a frame can free its node.
    drop(removed);
    Err(PyRuntimeError::new_err(
        "tracking frames are unbalanced: an untracked() block was left open inside a computation \
         or effect",
    ))
}

/// Whether the innermost frame is an untracked block.
pub(crate) fn in_untracked_block() -> bool {
    with_frames(|frames| matches!(frames.borrow().last(), Some(None)))
}

/// Whether `node` is being evaluated on this thread.
#[cold]
pub(crate) fn is_evaluating(node: &Rc<Node>) -> bool {
    with_frames(|frames| {
        frames
            .borrow()
            .iter()
            .any(|frame| frame.as_ref().is_some_and(|frame| Rc::ptr_eq(frame, node)))
    })
}

/// Whether a reactive read right now would register a dependency.
pub(crate) fn is_tracking() -> bool {
    with_frames(|frames| matches!(frames.borrow().last(), Some(Some(_))))
}

// ---------------------------------------------------------------------------
// Dependency links
// ---------------------------------------------------------------------------

pub(crate) fn track_read(node: &Rc<Node>, handle: &Bound<'_, PyAny>) {
    with_frames(|frames| {
        let frames = frames.borrow();
        if let Some(Some(reader)) = frames.last() {
            // Self-reads would make a node depend on itself.
            if !Rc::ptr_eq(reader, node) {
                register_dependency(reader, node, handle);
            }
        }
    })
}

/// Stamp `dep`'s link with the current run, adding the link if needed. While
/// a consumer runs, each of its dependencies records where its link is, so the
/// lookup needs no search. Only Rust allocations happen here, so holding
/// borrows is safe.
fn register_dependency(reader: &Rc<Node>, dep: &Rc<Node>, handle: &Bound<'_, PyAny>) {
    let consumer = reader.reader_state();
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
    let consumer = node.reader_state();
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
    let consumer = reader.reader_state();
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
        dep.observers.set_link(slot, position);
    }
    let key = node_key(reader);
    for link in &dropped {
        let slot = link.slot.get();
        if slot != NO_SLOT {
            link.node.observers.remove_consumer(slot, key);
        }
    }
    for (dep, position) in subscribe {
        let slot = dep.observers.push_consumer(Rc::downgrade(reader), position);
        if let Some(link) = consumer.deps.borrow().get(position as usize) {
            link.slot.set(slot);
        }
    }
    // Dropping a link can free its dependency, which can run Python code.
    drop(dropped);
}

/// Unsubscribe from every dependency and forget them.
pub(crate) fn detach_all_deps(reader: &Rc<Node>) {
    let Some(consumer) = reader.role.reader_state() else {
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
        .reader_state()
        .deps
        .borrow()
        .iter()
        .map(|link| link.handle.clone_ref(py))
        .collect();
    PyTuple::new(py, handles)
}

fn node_key(node: &Node) -> usize {
    node as *const Node as usize
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
            link.node.observers.remove_consumer(slot, key);
        }
    }
}
