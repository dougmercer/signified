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

use crate::node::{DepLink, Node, ReaderLink, NEVER, NO_SLOT};
use crate::{EngineError, Host};

// ---------------------------------------------------------------------------
// Tracking frames
// ---------------------------------------------------------------------------

type FrameStack<H> = RefCell<Vec<Option<Rc<Node<H>>>>>;

/// The consumers this thread is evaluating, innermost last; `None` marks an
/// untracked block. Part of the runtime.
pub(crate) struct Frames<H: Host>(FrameStack<H>);

impl<H: Host> Default for Frames<H> {
    fn default() -> Self {
        Frames(RefCell::new(Vec::new()))
    }
}

fn with_frames<H: Host, R>(f: impl FnOnce(&FrameStack<H>) -> R) -> R {
    H::with_runtime(|rt| f(&rt.frames.0))
}

/// Push a tracking frame (`None` for an untracked block) and return the depth
/// to pass to `end_frame`.
pub fn push_frame<H: Host>(frame: Option<Rc<Node<H>>>) -> usize {
    with_frames::<H, _>(|frames| {
        let mut frames = frames.borrow_mut();
        frames.push(frame);
        frames.len() - 1
    })
}

/// Pop the innermost frame. The caller drops it with nothing borrowed.
pub fn pop_frame<H: Host>() -> Option<Option<Rc<Node<H>>>> {
    with_frames::<H, _>(|frames| frames.borrow_mut().pop())
}

/// Remove the frame that `push_frame` returned `depth` for. If code inside
/// left an untracked block open, the frames above it are removed too and the
/// run fails, so later reads are not registered with the wrong consumer.
#[inline]
pub fn end_frame<H: Host>(depth: usize) -> Result<(), H::Error> {
    let popped = with_frames::<H, _>(|frames| {
        let mut frames = frames.borrow_mut();
        (frames.len() == depth + 1).then(|| frames.pop())
    });
    match popped {
        Some(frame) => {
            drop(frame);
            Ok(())
        }
        None => unbalanced_frames::<H>(depth),
    }
}

#[cold]
fn unbalanced_frames<H: Host>(depth: usize) -> Result<(), H::Error> {
    let removed = with_frames::<H, _>(|frames| {
        let mut frames = frames.borrow_mut();
        let keep = depth.min(frames.len());
        frames.split_off(keep)
    });
    // Dropping a frame can free its node.
    drop(removed);
    Err(H::engine_error(EngineError::UnbalancedFrames))
}

/// Whether the innermost frame is an untracked block.
pub fn in_untracked_block<H: Host>() -> bool {
    with_frames::<H, _>(|frames| matches!(frames.borrow().last(), Some(None)))
}

/// Whether `node` is being evaluated on this thread.
#[cold]
pub fn is_evaluating<H: Host>(node: &Rc<Node<H>>) -> bool {
    with_frames::<H, _>(|frames| {
        frames
            .borrow()
            .iter()
            .any(|frame| frame.as_ref().is_some_and(|frame| Rc::ptr_eq(frame, node)))
    })
}

/// Whether a reactive read right now would register a dependency.
pub fn is_tracking<H: Host>() -> bool {
    with_frames::<H, _>(|frames| matches!(frames.borrow().last(), Some(Some(_))))
}

// ---------------------------------------------------------------------------
// Dependency links
// ---------------------------------------------------------------------------

/// Register a read of `node` with the consumer that is running, if any.
/// `handle` makes the link's handle; it is called only for a new link.
#[inline]
pub fn track_read<H: Host>(node: &Rc<Node<H>>, handle: impl FnOnce() -> H::Handle) {
    with_frames::<H, _>(|frames| {
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
/// lookup needs no search. Only engine allocations happen here (and `handle`,
/// which must not run user code), so holding borrows is safe.
fn register_dependency<H: Host>(
    reader: &Rc<Node<H>>,
    dep: &Rc<Node<H>>,
    handle: impl FnOnce() -> H::Handle,
) {
    let consumer = reader.reader_state();
    let token = consumer.token.get();
    let read_version = dep.version.get();
    let key = reader.key();
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
        handle: handle(),
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
pub fn start_refresh<H: Host>(node: &Rc<Node<H>>) {
    let consumer = node.reader_state();
    consumer.token.set(consumer.token.get() + 1);
    let reader = node.key();
    for (position, link) in consumer.deps.borrow().iter().enumerate() {
        link.rollback.set(link.node.reader_link.get());
        link.node.reader_link.set(ReaderLink {
            reader,
            position: position as u32,
        });
    }
}

/// End a run: subscribe to every dependency it read and drop the rest. Call
/// it after successful and failed runs alike, so a consumer always depends on
/// exactly what its last run read.
pub fn commit_refresh<H: Host>(reader: &Rc<Node<H>>) {
    let consumer = reader.reader_state();
    let token = consumer.token.get();
    let mut subscribe: Vec<(Rc<Node<H>>, u32)> = Vec::new();
    let mut moved: Vec<(Rc<Node<H>>, u32, u32)> = Vec::new();
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
    let key = reader.key();
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
    // Dropping a link can free its dependency, which can run host code.
    drop(dropped);
}

/// Unsubscribe from every dependency and forget them.
pub fn detach_all_deps<H: Host>(reader: &Rc<Node<H>>) {
    let Some(consumer) = reader.role.reader_state() else {
        return;
    };
    let links = std::mem::take(&mut *consumer.deps.borrow_mut());
    unlink(reader.key(), &links);
    drop(links);
}

/// Unsubscribe a consumer (identified by `key`) from each of `links`, and
/// undo `register_dependency` bookkeeping that still points at it.
pub(crate) fn unlink<H: Host>(key: usize, links: &[DepLink<H>]) {
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
