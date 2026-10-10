//! Running effects and `subscribe()` observers. Both are queued during a
//! notification walk and run, in the order they were queued, once the
//! outermost walk or batch ends.

use std::collections::HashMap;
use std::rc::{Rc, Weak};

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyWeakrefReference};

use crate::graph::{self, rt, Compute, Node};

const MAX_RUNS: u32 = 100;

/// Work waiting in the queue.
pub(crate) enum Job {
    /// An effect, valid while its `queued` number is still `seq`.
    Effect { node: Weak<Node>, seq: u64 },
    /// A `subscribe()` observer's weak reference; its `update()` is called.
    Observer(Py<PyWeakrefReference>),
}

/// Queue `effect` unless it is disposed or already queued.
pub(crate) fn enqueue_effect(effect: &Rc<Node>) {
    let consumer = effect.consumer();
    if !consumer.active.get() || consumer.queued.get() != 0 {
        return;
    }
    let rt = rt();
    let seq = rt.pending_seq.get() + 1;
    rt.pending_seq.set(seq);
    consumer.queued.set(seq);
    rt.pending.borrow_mut().push_back(Job::Effect {
        node: Rc::downgrade(effect),
        seq,
    });
}

/// Queue a `subscribe()` observer unless it is already queued.
pub(crate) fn enqueue_observer(reference: Py<PyWeakrefReference>) {
    let rt = rt();
    let fresh = rt
        .queued_observers
        .borrow_mut()
        .insert(reference.as_ptr() as usize);
    if fresh {
        rt.pending.borrow_mut().push_back(Job::Observer(reference));
    }
}

/// Queue `effect`, then run the queue unless a walk, batch or flush is in
/// progress.
pub(crate) fn schedule(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
    enqueue_effect(effect);
    flush(py)
}

/// Drop a queued run of `effect`, if any.
pub(crate) fn discard(effect: &Node) {
    effect.consumer().queued.set(0);
}

/// Run queued work in order. One failure is raised directly and several as an
/// `ExceptionGroup`. Something that keeps queuing itself stops the flush after
/// `MAX_RUNS` runs.
pub(crate) fn flush(py: Python<'_>) -> PyResult<()> {
    let rt = rt();
    if rt.pending.borrow().is_empty()
        || rt.flushing.get()
        || rt.batch_depth.get() > 0
        || rt.wave_depth.get() > 0
    {
        return Ok(());
    }
    rt.flushing.set(true);
    let epoch = rt.flush_epoch.get() + 1;
    rt.flush_epoch.set(epoch);
    let mut errors = Vec::new();
    // Holds each observer's weak reference, so its address stays unique.
    let mut observer_runs: HashMap<usize, (Py<PyWeakrefReference>, u32)> = HashMap::new();
    let outcome = run_pending(py, epoch, &mut observer_runs, &mut errors);
    // Whatever is left was abandoned by an error.
    let abandoned = std::mem::take(&mut *rt.pending.borrow_mut());
    rt.queued_observers.borrow_mut().clear();
    for job in &abandoned {
        if let Job::Effect { node, seq } = job {
            if let Some(effect) = node.upgrade() {
                if effect.consumer().queued.get() == *seq {
                    effect.consumer().queued.set(0);
                }
            }
        }
    }
    rt.flushing.set(false);
    drop(abandoned);
    drop(observer_runs);
    outcome?;
    raise_errors(py, errors)
}

fn run_pending(
    py: Python<'_>,
    epoch: u64,
    observer_runs: &mut HashMap<usize, (Py<PyWeakrefReference>, u32)>,
    errors: &mut Vec<PyErr>,
) -> PyResult<()> {
    let rt = rt();
    loop {
        let job = rt.pending.borrow_mut().pop_front();
        let Some(job) = job else {
            return Ok(());
        };
        let outcome = match job {
            Job::Effect { node, seq } => {
                let Some(effect) = node.upgrade() else {
                    continue;
                };
                let consumer = effect.consumer();
                // Discarded, or queued again since.
                if consumer.queued.get() != seq {
                    continue;
                }
                consumer.queued.set(0);
                if !consumer.active.get() {
                    continue;
                }
                if consumer.run_epoch.get() != epoch {
                    consumer.run_epoch.set(epoch);
                    consumer.runs.set(0);
                }
                consumer.runs.set(consumer.runs.get() + 1);
                if consumer.runs.get() > MAX_RUNS {
                    errors.push(PyRuntimeError::new_err(format!(
                        "Effect did not settle after {MAX_RUNS} runs"
                    )));
                    return Ok(());
                }
                run(py, &effect)
            }
            Job::Observer(reference) => {
                let key = reference.as_ptr() as usize;
                rt.queued_observers.borrow_mut().remove(&key);
                let Some(target) = reference.bind(py).upgrade() else {
                    continue;
                };
                let entry = observer_runs.entry(key).or_insert_with(|| (reference, 0));
                entry.1 += 1;
                if entry.1 > MAX_RUNS {
                    errors.push(PyRuntimeError::new_err(format!(
                        "Observer did not settle after {MAX_RUNS} runs"
                    )));
                    return Ok(());
                }
                target.call_method0(intern!(py, "update")).map(drop)
            }
        };
        match outcome {
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
fn run(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
    let consumer = effect.consumer();
    if consumer.has_run.get() && !graph::dependencies_changed(py, effect)? {
        return Ok(());
    }
    // Refreshing a dependency can dispose this effect through user code.
    if !consumer.active.get() {
        return Ok(());
    }
    consumer.has_run.set(true);
    let function = consumer
        .compute
        .borrow()
        .as_ref()
        .map(|compute| match compute {
            Compute::Function(f) | Compute::Source(f) | Compute::Call { func: f, .. } => {
                f.clone_ref(py)
            }
        });
    let Some(function) = function else {
        return Ok(());
    };
    graph::start_refresh(effect);
    graph::push_frame(Some(effect.clone()));
    let result = function.bind(py).call0();
    graph::pop_frame();
    if consumer.active.get() {
        // Subscribe to what this run read, even if it raised, so a change to
        // any of it retries the callback.
        graph::commit_refresh(effect);
    } else {
        graph::detach_all_deps(effect);
    }
    drop(function);
    drop(result?);
    // Also catches writes after a read during the first run, before the
    // subscriptions existed.
    if consumer.active.get() && graph::invalidated_since_read(effect) {
        schedule(py, effect)?;
    }
    Ok(())
}
