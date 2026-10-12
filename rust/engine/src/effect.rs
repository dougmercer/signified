//! Running an effect: a callback re-run when what it read changes.

use std::rc::Rc;

use crate::node::Node;
use crate::refresh::{dependencies_changed, invalidated_since_read};
use crate::{scheduler, tracking, Host};

/// Run `effect` if it has never run or its dependencies changed since its
/// last run (for [`Host::run_effect`]). `prepare` returns what to call, or
/// `None` to skip the run; `call` runs it with the effect's reads tracked.
/// What `prepare` returned is dropped after the run is committed.
pub fn run<H: Host, C>(
    cx: H::Cx<'_>,
    effect: &Rc<Node<H>>,
    prepare: impl FnOnce() -> Option<C>,
    call: impl FnOnce(&C) -> Result<(), H::Error>,
) -> Result<(), H::Error> {
    let state = effect.effect_state();
    if state.has_run.get() && !dependencies_changed(cx, effect)? {
        return Ok(());
    }
    // Refreshing a dependency can dispose this effect through user code.
    if !state.active.get() {
        return Ok(());
    }
    state.has_run.set(true);
    let Some(callable) = prepare() else {
        return Ok(());
    };
    tracking::start_refresh(effect);
    let depth = tracking::push_frame(Some(effect.clone()));
    let mut result = call(&callable);
    if let Err(error) = tracking::end_frame::<H>(depth) {
        result = Err(error);
    }
    if state.active.get() {
        // Subscribe to what this run read, even if it failed, so a change to
        // any of it retries the callback.
        tracking::commit_refresh(effect);
    } else {
        tracking::detach_all_deps(effect);
    }
    drop(callable);
    result?;
    // Also catches writes after a read during the first run, before the
    // subscriptions existed.
    if state.active.get() && invalidated_since_read(effect) {
        scheduler::schedule(cx, effect)?;
    }
    Ok(())
}
