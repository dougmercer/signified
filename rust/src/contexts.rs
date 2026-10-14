//! `untracked()`, `batch()` and `is_tracking()`: the engine's tracking frames
//! and batches, for Python.

use pyo3::exceptions::PyRuntimeError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use crate::engine::{scheduler, tracking};

/// Whether a reactive read right now would register a dependency.
#[pyfunction]
pub fn is_tracking() -> bool {
    tracking::is_tracking()
}

/// Raise `RuntimeError` if a Computed is being evaluated, before a signal's
/// wrapped object is changed in place.
#[pyfunction]
pub fn check_change_allowed() -> PyResult<()> {
    tracking::check_change_allowed()
}

/// `with untracked():` reads inside do not subscribe the enclosing
/// computation or effect.
#[pyclass(frozen, module = "signified._core", name = "Untracked")]
pub struct Untracked;

#[pymethods]
impl Untracked {
    #[new]
    fn new() -> Self {
        Untracked
    }

    fn __enter__(&self) {
        tracking::push_frame(None);
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&self, _exc: &Bound<'_, PyTuple>) -> PyResult<bool> {
        // Check before popping, so a mismatch cannot remove a computation's frame.
        if !tracking::in_untracked_block() {
            return Err(PyRuntimeError::new_err(
                "untracked() exited without a matching enter",
            ));
        }
        drop(tracking::pop_frame());
        Ok(false)
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
        scheduler::begin_batch();
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: &Bound<'_, PyAny>,
        exc: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        let flushed = scheduler::end_batch(py);
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
