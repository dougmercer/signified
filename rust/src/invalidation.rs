//! Push: when a value changes, mark the computeds that depend on it stale
//! and queue the effects and `subscribe()` observers that depend on it.

use std::rc::Rc;

use pyo3::prelude::*;
use pyo3::types::PyWeakrefReference;

use crate::node::{Kind, Node, State};
use crate::observer_list::Observer;
use crate::runtime::rt;
use crate::scheduler;

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

/// Counts one notification walk in `wave_depth` while it lives, so a panic
/// that unwinds through a walk cannot leave the count raised and stop every
/// later flush.
struct Walking;

impl Walking {
    fn enter() -> Walking {
        let depth = &rt().wave_depth;
        depth.set(depth.get() + 1);
        Walking
    }
}

impl Drop for Walking {
    fn drop(&mut self) {
        let depth = &rt().wave_depth;
        depth.set(depth.get() - 1);
    }
}

/// Tell `start`'s observers it changed: mark dependent computeds stale,
/// depth-first, and queue dependent effects and `subscribe()` observers.
/// No Python code runs during the walk. Queued work runs once the outermost
/// walk ends, unless a batch or flush is in progress.
pub(crate) fn notify(py: Python<'_>, start: &Rc<Node>) -> PyResult<()> {
    if start.observers.is_empty() {
        return Ok(());
    }
    let walking = Walking::enter();
    walk(py, start);
    drop(walking);
    if rt().wave_depth.get() == 0 {
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
        let step = match node.observers.get(*index).as_deref() {
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
                    if invalidate(&consumer, false) && !consumer.observers.is_empty() {
                        stack.push((consumer, 0));
                    }
                }
                Kind::Signal => unreachable!("signals do not read other nodes"),
            },
            Step::Python(reference) => scheduler::enqueue_observer(reference),
        }
    }
}
