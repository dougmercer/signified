//! Push: when a value changes, mark the computeds that depend on it stale
//! and queue the effects and `_subscribe()` observers that depend on it.

use std::cell::Cell;
use std::rc::{Rc, Weak};

use pyo3::prelude::*;
use pyo3::types::PyWeakrefReference;

use crate::engine::node::{ComputedState, Node, Role, State};
use crate::engine::observer_list::Observer;
use crate::engine::runtime::with_rt;
use crate::engine::scheduler;

/// Mark stale and return whether observers still need to hear about it.
/// `force` upgrades to `MustRefresh`, bypassing the dependency check.
pub(crate) fn invalidate(computed: &ComputedState, force: bool) -> bool {
    let target = if force {
        State::MustRefresh
    } else {
        State::Stale
    };
    if computed.state.get() < target {
        computed.state.set(target);
    }
    if computed.notified.get() {
        return false;
    }
    computed.notified.set(true);
    true
}

/// Counts one notification walk in `wave_depth` while it lives, so a panic
/// that unwinds through a walk cannot leave the count raised and stop every
/// later flush.
struct Walking<'a>(&'a Cell<u32>);

impl Walking<'_> {
    fn enter(depth: &Cell<u32>) -> Walking<'_> {
        depth.set(depth.get() + 1);
        Walking(depth)
    }
}

impl Drop for Walking<'_> {
    fn drop(&mut self) {
        self.0.set(self.0.get() - 1);
    }
}

/// Tell `start`'s observers it changed: mark dependent computeds stale,
/// depth-first, and queue dependent effects and `_subscribe()` observers.
/// No Python code runs during the walk. Queued work runs once the outermost
/// walk ends, unless a batch or flush is in progress.
///
/// A computed is a start only when invalidated explicitly, and then the
/// samples that computed it for themselves must evaluate again too.
pub(crate) fn notify(py: Python<'_>, start: &Rc<Node>) -> PyResult<()> {
    let samplers = samplers_of(start);
    if start.observers.is_empty() && samplers.is_empty() {
        return Ok(());
    }
    let outermost = with_rt(|rt| {
        let walking = Walking::enter(&rt.wave_depth);
        walk(py, start);
        for sampler in &samplers {
            if invalidate(sampler.computed_state(), true) && !sampler.observers.is_empty() {
                walk(py, sampler);
            }
        }
        drop(walking);
        rt.wave_depth.get() == 0
    });
    if outermost {
        scheduler::flush(py)?;
    }
    Ok(())
}

/// The live samples that computed `node` for themselves.
fn samplers_of(node: &Node) -> Vec<Rc<Node>> {
    match &node.role {
        Role::Computed(computed) => computed
            .samplers
            .borrow()
            .iter()
            .filter_map(Weak::upgrade)
            .collect(),
        _ => Vec::new(),
    }
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
            Step::Consumer(consumer) => match &consumer.role {
                Role::Effect(_) => scheduler::enqueue_effect(&consumer),
                Role::Computed(computed) => {
                    if invalidate(computed, false) && !consumer.observers.is_empty() {
                        stack.push((consumer, 0));
                    }
                }
                Role::Signal => unreachable!("signals do not read other nodes"),
            },
            Step::Python(reference) => scheduler::enqueue_observer(reference),
        }
    }
}
