//! Engine nodes owned by Python objects. Nodes use `Rc` and `Cell`, so they
//! are neither `Send` nor `Sync`, which a `#[pyclass]` must be. This is where
//! the single-threaded engine meets Python's threads.

use std::rc::{Rc, Weak};

use crate::engine::node::{Node, Role};

/// `Rc<Node>` made `Send` and `Sync` so a Python object can own one.
///
/// SAFETY: nodes are only touched while attached to an interpreter that holds
/// the GIL, which lets one thread run at a time (the module is
/// `gil_used = true`), so the non-atomic reference counts and the cells are
/// never accessed concurrently. No borrow is held across a call into Python,
/// so a thread switch inside such a call never observes a cell mid-update.
/// Each thread tracks and schedules on its own; using one graph from several
/// threads at the same time is unsupported, but it cannot cause a data race.
/// Thread-exit cleanup runs without the GIL, so work a thread leaves queued is
/// leaked rather than dropped; see the engine's `Queue`.
pub(crate) struct Shared(pub(crate) Rc<Node>);

unsafe impl Send for Shared {}
unsafe impl Sync for Shared {}

impl Shared {
    pub(crate) fn new(role: Role) -> Shared {
        Shared(Rc::new(Node::new(role)))
    }
}

impl std::ops::Deref for Shared {
    type Target = Rc<Node>;

    fn deref(&self) -> &Rc<Node> {
        &self.0
    }
}

/// `Weak<Node>` made `Send` and `Sync`, for the same reason as `Shared`.
pub(crate) struct WeakShared(pub(crate) Weak<Node>);

unsafe impl Send for WeakShared {}
unsafe impl Sync for WeakShared {}
