//! `_subscribe()` observers: objects whose `update()` runs after a value they
//! subscribed to changes, like an effect. Each is held weakly and removed
//! from the node's observer list once it dies.

use std::rc::Rc;

use pyo3::prelude::*;
use pyo3::types::PyWeakrefReference;

use crate::node::{Node, WeakShared};
use crate::observer_list::Observer;
use crate::scheduler;

/// A `_subscribe()` observer's weak-reference callback: removes the
/// observer, whose address was `id`, from its node once it dies.
#[pyclass(frozen, module = "signified._core", name = "ObserverCleanup")]
pub struct ObserverCleanup {
    node: WeakShared,
    id: usize,
}

#[pymethods]
impl ObserverCleanup {
    fn __call__(&self, reference: &Bound<'_, PyAny>) {
        if let Some(node) = self.node.0.upgrade() {
            forget_observer(&node, self.id, reference.as_ptr());
        }
    }
}

/// The slot of `observer` in `node`'s observer list, if subscribed.
fn find_python_observer(node: &Node, observer: &Bound<'_, PyAny>) -> Option<u32> {
    let py = observer.py();
    let id = observer.as_ptr() as usize;
    let slot = node.observers.subscriber_slot(id)?;
    let reference = match node.observers.get(slot as usize).as_deref() {
        Some(Observer::Python {
            reference,
            id: other,
        }) if *other == id => reference.clone_ref(py),
        _ => return None,
    };
    // An observer that died at this address may not have been removed yet.
    let alive = reference
        .bind(py)
        .upgrade()
        .is_some_and(|target| target.is(observer));
    alive.then_some(slot)
}

pub(crate) fn add_python_observer(node: &Rc<Node>, observer: &Bound<'_, PyAny>) -> PyResult<()> {
    if find_python_observer(node, observer).is_some() {
        return Ok(());
    }
    let py = observer.py();
    let id = observer.as_ptr() as usize;
    // The callback removes the entry as soon as the observer dies.
    let cleanup = Py::new(
        py,
        ObserverCleanup {
            node: WeakShared(Rc::downgrade(node)),
            id,
        },
    )?;
    let reference = PyWeakrefReference::new_with(observer, cleanup.bind(py))?.unbind();
    node.observers.push_subscriber(reference, id);
    Ok(())
}

/// Remove the `_subscribe()` observer whose weak reference is `reference`
/// and whose address was `id` (called from that reference's callback, once
/// the observer has died).
fn forget_observer(node: &Node, id: usize, reference: *mut pyo3::ffi::PyObject) {
    let holds_reference = |slot: usize| {
        matches!(
            node.observers.get(slot).as_deref(),
            Some(Observer::Python { reference: entry, .. }) if entry.as_ptr() == reference
        )
    };
    let slot = match node.observers.subscriber_slot(id) {
        Some(slot) if holds_reference(slot as usize) => Some(slot),
        // A new observer at the same address took over the record; search.
        _ => (0..node.observers.slot_count())
            .find(|&slot| holds_reference(slot))
            .map(|slot| slot as u32),
    };
    if let Some(slot) = slot {
        drop(node.observers.vacate(slot));
    }
}

/// Unsubscribe `observer`, including a queued call of its `update()`.
pub(crate) fn remove_python_observer(node: &Node, observer: &Bound<'_, PyAny>) {
    let Some(slot) = find_python_observer(node, observer) else {
        return;
    };
    let removed = node.observers.vacate(slot);
    if let Observer::Python { reference, .. } = &removed {
        scheduler::cancel_observer(reference.as_ptr() as usize);
    }
    drop(removed);
}

/// Live observers of `node`; dead `_subscribe()` observers are removed.
pub(crate) fn live_observer_count(py: Python<'_>, node: &Node) -> usize {
    let mut count = 0;
    let mut dead = Vec::new();
    let mut slot = 0;
    loop {
        let alive = match node.observers.get(slot).as_deref() {
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
    let removed: Vec<Observer> = dead
        .into_iter()
        .map(|slot| node.observers.take(slot))
        .collect();
    node.observers.compact_if_sparse();
    drop(removed);
    count
}
