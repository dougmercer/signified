//! Synchronous effect scheduling: effects run after the outermost
//! notification wave or batch, in the order they were scheduled.

use std::collections::HashMap;
use std::sync::{Arc, Weak};

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::PyList;

use crate::graph::{self, rt, Compute, Node};

const MAX_RUNS_PER_EFFECT: u32 = 100;

fn key(node: &Node) -> usize {
    node as *const Node as usize
}

/// Queue `effect` to run, then run the queue unless a wave, batch or flush is
/// in progress. An effect already queued keeps its place.
pub(crate) fn schedule(py: Python<'_>, effect: &Arc<Node>) -> PyResult<()> {
    if !effect.active.get() {
        return Ok(());
    }
    let rt = rt();
    let key = key(effect);
    let queued = rt.pending_index.borrow().contains_key(&key);
    if !queued {
        let seq = rt.pending_seq.get() + 1;
        rt.pending_seq.set(seq);
        rt.pending_index.borrow_mut().insert(key, seq);
        rt.pending
            .borrow_mut()
            .push_back((Arc::downgrade(effect), seq));
    }
    flush(py)
}

/// Drop a pending run of `effect`, if any.
pub(crate) fn discard(effect: &Node) {
    rt().pending_index.borrow_mut().remove(&key(effect));
}

/// Run pending effects in order. One failure is raised directly and several
/// as an `ExceptionGroup`; an effect that keeps rescheduling itself stops the
/// flush after `MAX_RUNS_PER_EFFECT` runs.
pub(crate) fn flush(py: Python<'_>) -> PyResult<()> {
    let rt = rt();
    if rt.pending_index.borrow().is_empty()
        || rt.flushing.get()
        || rt.batch_depth.get() > 0
        || rt.wave_depth.get() > 0
    {
        return Ok(());
    }
    rt.flushing.set(true);
    let mut errors = Vec::new();
    // Weak keys keep an address from being reused by another effect mid-flush.
    let mut runs: HashMap<usize, (Weak<Node>, u32)> = HashMap::new();
    let outcome = run_pending(py, &mut runs, &mut errors);
    rt.pending.borrow_mut().clear();
    rt.pending_index.borrow_mut().clear();
    rt.flushing.set(false);
    drop(runs);
    outcome?;
    raise_errors(py, errors)
}

fn run_pending(
    py: Python<'_>,
    runs: &mut HashMap<usize, (Weak<Node>, u32)>,
    errors: &mut Vec<PyErr>,
) -> PyResult<()> {
    let rt = rt();
    loop {
        let next = rt.pending.borrow_mut().pop_front();
        let Some((weak, seq)) = next else {
            return Ok(());
        };
        let key = weak.as_ptr() as usize;
        {
            let mut index = rt.pending_index.borrow_mut();
            // Discarded, or superseded by a later schedule.
            if index.get(&key) != Some(&seq) {
                continue;
            }
            index.remove(&key);
        }
        let Some(effect) = weak.upgrade() else {
            continue;
        };
        if !effect.active.get() {
            continue;
        }
        let entry = runs.entry(key).or_insert_with(|| (weak.clone(), 0));
        entry.1 += 1;
        if entry.1 > MAX_RUNS_PER_EFFECT {
            errors.push(PyRuntimeError::new_err(format!(
                "Effect did not settle after {MAX_RUNS_PER_EFFECT} runs"
            )));
            return Ok(());
        }
        match run(py, &effect) {
            Ok(()) => {}
            Err(error) if error.is_instance_of::<PyException>(py) => errors.push(error),
            Err(error) => return Err(error),
        }
    }
}

fn raise_errors(py: Python<'_>, mut errors: Vec<PyErr>) -> PyResult<()> {
    match errors.len() {
        0 => Ok(()),
        1 => Err(errors.remove(0)),
        _ => {
            let exceptions = PyList::new(py, errors.into_iter().map(|error| error.into_value(py)))?;
            let group = py
                .import(intern!(py, "builtins"))?
                .getattr(intern!(py, "ExceptionGroup"))?
                .call1(("Signified effect failures", exceptions))?;
            Err(PyErr::from_value(group))
        }
    }
}

/// Run one effect if its dependencies changed since its last run.
fn run(py: Python<'_>, effect: &Arc<Node>) -> PyResult<()> {
    if effect.has_run.get() && !graph::dependencies_changed(py, effect)? {
        return Ok(());
    }
    // Refreshing a dependency can dispose this effect through user code.
    if !effect.active.get() {
        return Ok(());
    }
    effect.has_run.set(true);
    let compute = effect
        .compute
        .borrow()
        .as_ref()
        .map(|compute| match compute {
            Compute::Function(f) => f.clone_ref(py),
            Compute::Call { func, .. } => func.clone_ref(py),
        });
    let Some(function) = compute else {
        return Ok(());
    };
    graph::start_refresh(effect);
    graph::push_frame(Some(effect.clone()));
    let result = function.bind(py).call0();
    graph::pop_frame();
    if effect.active.get() {
        // Subscribe to what this run read, even if it raised, so a change to
        // any of it retries the callback.
        graph::commit_refresh(py, effect, None);
    } else {
        graph::detach_all_deps(py, effect, None);
    }
    drop(function);
    drop(result?);
    // Also catches writes after a read during the first run, before the
    // subscriptions existed.
    if effect.active.get() && graph::invalidated_since_read(effect) {
        schedule(py, effect)?;
    }
    Ok(())
}
