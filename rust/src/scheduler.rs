//! `batch()`, and the Python host's part of running the queue: calling
//! `_subscribe()` observers and reporting failures. The queue itself is the
//! engine's.

use std::collections::HashMap;

use pyo3::exceptions::PyRuntimeError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyWeakrefReference};
use signified_engine::scheduler::{self, MAX_RUNS};
use signified_engine::Step;

use crate::host::PyHost;

/// Runs per observer in one flush, keyed by its address and checked against
/// a weak reference to it.
pub(crate) type ObserverRuns = HashMap<usize, (Py<PyWeakrefReference>, u32)>;

/// Cancel a queued call of the observer whose weak reference is `reference`.
pub(crate) fn cancel_observer(reference: usize) {
    scheduler::cancel_subscriber::<PyHost>(reference);
}

/// Call a queued `_subscribe()` observer's `update()`, unless it died.
pub(crate) fn run_observer(
    py: Python<'_>,
    reference: Py<PyWeakrefReference>,
    observer_runs: &mut ObserverRuns,
) -> Step<PyErr> {
    let Some(target) = reference.bind(py).upgrade() else {
        return Step::Done;
    };
    // Count runs per observer, not per subscription, so an observer that
    // resubscribes itself still reaches the limit. The entry keeps a weak
    // reference to its observer: one whose observer died, and whose address
    // was reused, starts over.
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
        return Step::Stop(PyRuntimeError::new_err(format!(
            "Observer did not settle after {MAX_RUNS} runs"
        )));
    }
    match target.call_method0(intern!(py, "update")) {
        Ok(_) => Step::Done,
        Err(error) => Step::Failed(error),
    }
}

/// One failure is raised directly and several as an `ExceptionGroup`.
pub(crate) fn raise_errors(py: Python<'_>, mut errors: Vec<PyErr>) -> PyResult<()> {
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
        scheduler::begin_batch::<PyHost>();
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: &Bound<'_, PyAny>,
        exc: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        let flushed = scheduler::end_batch::<PyHost>(py);
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
