//! Push: when a value changes, mark the computeds that depend on it stale
//! and queue the effects and subscribers that depend on it.

use std::cell::Cell;
use std::rc::Rc;

use crate::node::{ComputedState, Node, Role, State};
use crate::observers::Observer;
use crate::scheduler;
use crate::Host;

/// Mark stale and return whether observers still need to hear about it.
/// `force` upgrades to `MustRefresh`, bypassing the dependency check.
pub fn invalidate<H: Host>(computed: &ComputedState<H>, force: bool) -> bool {
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
/// depth-first, and queue dependent effects and subscribers. No host code
/// runs during the walk. Queued work runs once the outermost walk ends,
/// unless a batch or flush is in progress.
pub fn notify<H: Host>(cx: H::Cx<'_>, start: &Rc<Node<H>>) -> Result<(), H::Error> {
    if start.observers.is_empty() {
        return Ok(());
    }
    let outermost = H::with_runtime(|rt| {
        let walking = Walking::enter(&rt.wave_depth);
        walk(cx, start);
        drop(walking);
        rt.wave_depth.get() == 0
    });
    if outermost {
        scheduler::flush::<H>(cx)?;
    }
    Ok(())
}

enum Step<H: Host> {
    Done,
    Skip,
    Consumer(Rc<Node<H>>),
    Subscriber(H::Subscriber),
}

/// Depth-first, with an explicit stack so long chains cannot overflow.
fn walk<H: Host>(cx: H::Cx<'_>, start: &Rc<Node<H>>) {
    let mut stack: Vec<(Rc<Node<H>>, usize)> = vec![(start.clone(), 0)];
    while let Some((node, index)) = stack.last_mut() {
        let step = match node.observers.get(*index).as_deref() {
            None => Step::Done,
            Some(Observer::Vacant) => Step::Skip,
            Some(Observer::Consumer { node, .. }) => {
                node.upgrade().map_or(Step::Skip, Step::Consumer)
            }
            Some(Observer::Subscriber { subscriber, .. }) => {
                Step::Subscriber(H::clone_subscriber(cx, subscriber))
            }
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
            Step::Subscriber(subscriber) => scheduler::enqueue_subscriber::<H>(subscriber),
        }
    }
}
