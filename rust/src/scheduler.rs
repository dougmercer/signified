//! The queue of effects and `subscribe()` observers waiting to run, and
//! `batch()`. Both kinds of work are queued during a notification walk and
//! run, in the order they were queued, once the outermost walk or batch ends.

use std::collections::HashMap;
use std::rc::{Rc, Weak};

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyWeakrefReference};

use crate::node::Node;
use crate::runtime::rt;

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

/// Cancel a queued call of the observer whose weak reference is `reference`.
pub(crate) fn cancel_observer(reference: usize) {
    rt().queued_observers.borrow_mut().remove(&reference);
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
    // Runs per observer, keyed by its address and checked against a weak
    // reference to it.
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
                crate::effect::run(py, &effect)
            }
            Job::Observer(reference) => {
                let key = reference.as_ptr() as usize;
                // Unsubscribed since it was queued.
                if !rt.queued_observers.borrow_mut().remove(&key) {
                    continue;
                }
                let Some(target) = reference.bind(py).upgrade() else {
                    continue;
                };
                // Count runs per observer, not per subscription, so an observer
                // that resubscribes itself still reaches the limit. The entry
                // keeps a weak reference to its observer: one whose observer
                // died, and whose address was reused, starts over.
                let entry = observer_runs
                    .entry(target.as_ptr() as usize)
                    .or_insert_with(|| (reference.clone_ref(py), 0));
                let same_observer = entry
                    .0
                    .bind(py)
                    .upgrade()
                    .is_some_and(|seen| seen.is(&target));
                if !same_observer {
                    *entry = (reference.clone_ref(py), 0);
                }
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

/// `with batch():` defers effects and observers until the outermost batch
/// exits. A body exception together with flush failures is raised as a
/// `BaseExceptionGroup`.
#[pyclass(frozen, module = "signified._core", name = "Batch")]
pub struct Batch;

#[pymethods]
impl Batch {
    #[new]
    fn new() -> Self {
        Batch
    }

    fn __enter__(&self) {
        let rt = rt();
        rt.batch_depth.set(rt.batch_depth.get() + 1);
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: &Bound<'_, PyAny>,
        exc: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        let rt = rt();
        rt.batch_depth.set(rt.batch_depth.get().saturating_sub(1));
        let flushed = flush(py);
        if exc.is_none() {
            flushed?;
            return Ok(false);
        }
        let Err(flush_error) = flushed else {
            // Re-raise the body's exception unchanged.
            return Ok(false);
        };
        let group = py
            .import(intern!(py, "builtins"))?
            .getattr(intern!(py, "BaseExceptionGroup"))?
            .call1((
                "Signified batch body and effect failures",
                (exc, flush_error.into_value(py)),
            ))?;
        // Like `raise ... from None`.
        group.setattr(intern!(py, "__suppress_context__"), true)?;
        Err(PyErr::from_value(group))
    }
}
