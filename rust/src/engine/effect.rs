//! Running an effect: a callback re-run when what it read changes.

use std::rc::Rc;

use pyo3::prelude::*;

use crate::engine::node::Node;
use crate::engine::{refresh, scheduler, tracking};

/// Run one effect if its dependencies changed since its last run.
pub(crate) fn run(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
    let state = effect.effect_state();
    if state.has_run.get() && !refresh::dependencies_changed(py, effect)? {
        return Ok(());
    }
    // Refreshing a dependency can dispose this effect through user code.
    if !state.active.get() {
        return Ok(());
    }
    state.has_run.set(true);
    let function = state
        .function
        .borrow()
        .as_ref()
        .map(|function| function.clone_ref(py));
    let Some(function) = function else {
        return Ok(());
    };
    tracking::start_refresh(effect);
    let depth = tracking::push_frame(Some(effect.clone()));
    let mut result = function.bind(py).call0().map(drop);
    if let Err(error) = tracking::end_frame(depth) {
        result = Err(error);
    }
    if state.active.get() {
        // Subscribe to what this run read, even if it raised, so a change to
        // any of it retries the callback.
        tracking::commit_refresh(effect);
    } else {
        tracking::detach_all_deps(effect);
    }
    drop(function);
    result?;
    // Also catches writes after a read during the first run, before the
    // subscriptions existed.
    if state.active.get() && refresh::invalidated_since_read(effect) {
        scheduler::schedule(py, effect)?;
    }
    Ok(())
}
