//! Push: when a value changes, mark the computeds that depend on it stale
//! and queue the effects and `subscribe()` observers that depend on it.

use std::rc::Rc;

use pyo3::prelude::*;
use pyo3::types::PyWeakrefReference;

use crate::node::{Kind, Node, Observer, State};
use crate::runtime::rt;
use crate::scheduler;
use crate::tracking::has_observers;

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
        scheduler::flush(py)?;
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
                Kind::Effect => scheduler::enqueue_effect(&consumer),
                Kind::Computed => {
                    if invalidate(&consumer, false) && has_observers(&consumer) {
                        stack.push((consumer, 0));
                    }
                }
                Kind::Signal => unreachable!("signals do not read other nodes"),
            },
            Step::Python(reference) => scheduler::enqueue_observer(reference),
        }
    }
}
