//! State shared by the whole engine, and the version clock.

use std::cell::{Cell, RefCell};
use std::collections::{HashSet, VecDeque};
use std::rc::Rc;
use std::sync::OnceLock;

use pyo3::prelude::*;

use crate::node::Node;
use crate::scheduler::Job;

pub(crate) struct Runtime {
    clock: Cell<u64>,
    /// The consumer being evaluated, innermost last; `None` marks an untracked block.
    pub(crate) frames: RefCell<Vec<Option<Rc<Node>>>>,
    /// Nesting of notification walks; effects run when it returns to zero.
    pub(crate) wave_depth: Cell<u32>,
    /// Effects and observers waiting to run, in the order they were queued.
    pub(crate) pending: RefCell<VecDeque<Job>>,
    pub(crate) pending_seq: Cell<u64>,
    /// Weak references of observers waiting in `pending`. A queued observer
    /// whose reference is missing was unsubscribed and is skipped.
    pub(crate) queued_observers: RefCell<HashSet<usize>>,
    pub(crate) flush_epoch: Cell<u64>,
    pub(crate) batch_depth: Cell<u32>,
    pub(crate) flushing: Cell<bool>,
    /// The plugin manager's `hook` object, when hooks are on.
    pub(crate) hooks: RefCell<Option<Py<PyAny>>>,
    /// The hooks a plugin implements, indexed by `hooks::Hook`, and one bit
    /// per hook in `hooks_on`.
    pub(crate) hook_callers: RefCell<[Option<Py<PyAny>>; 3]>,
    pub(crate) hooks_on: Cell<u8>,
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
        pending: RefCell::new(VecDeque::new()),
        pending_seq: Cell::new(0),
        queued_observers: RefCell::new(HashSet::new()),
        flush_epoch: Cell::new(0),
        batch_depth: Cell::new(0),
        flushing: Cell::new(false),
        hooks: RefCell::new(None),
        hook_callers: RefCell::new([None, None, None]),
        hooks_on: Cell::new(0),
    })
}

pub(crate) fn clock() -> u64 {
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
