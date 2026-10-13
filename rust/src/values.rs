//! Python values meeting the engine: recognizing and unwrapping reactive
//! values, and deciding whether a new value counts as a change.

use std::rc::Rc;

use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyComplex, PyFloat, PyInt, PyString};

use crate::computed::{read_computed, ComputedCore};
use crate::engine::node::Node;
use crate::engine::tracking::{end_frame, push_frame};
use crate::signal::{read_signal, SignalCore};

/// Whether `obj` is a reactive value (a Signal, Computed or Binding).
#[pyfunction]
pub fn is_reactive(obj: &Bound<'_, PyAny>) -> bool {
    obj.is_instance_of::<SignalCore>() || obj.is_instance_of::<ComputedCore>()
}

/// Unwrap exactly one reactive boundary: a Signal, Computed or Binding gives
/// its value (a dependency read, inside a computation); anything else is
/// returned unchanged.
#[pyfunction]
pub fn unref<'py>(py: Python<'py>, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    if value.is_none()
        || value.is_exact_instance_of::<PyFloat>()
        || value.is_exact_instance_of::<PyInt>()
        || value.is_exact_instance_of::<PyString>()
        || value.is_exact_instance_of::<PyBool>()
    {
        return Ok(value.clone());
    }
    // Subclasses are read natively too.
    if let Ok(signal) = value.cast::<SignalCore>() {
        return read_signal(py, &signal.get().node, value);
    }
    if let Ok(computed) = value.cast::<ComputedCore>() {
        return read_computed(py, &computed.get().node, value);
    }
    Ok(value.clone())
}

/// The engine node behind a Signal, Computed or Binding.
pub(crate) fn node_of(obj: &Bound<'_, PyAny>) -> PyResult<Rc<Node>> {
    if let Ok(signal) = obj.cast::<SignalCore>() {
        return Ok(Rc::clone(&signal.get().node));
    }
    if let Ok(computed) = obj.cast::<ComputedCore>() {
        return Ok(Rc::clone(&computed.get().node));
    }
    Err(PyTypeError::new_err(format!(
        "expected a Signal, Computed or Binding, got {}",
        obj.get_type().name()?
    )))
}

/// Exact built-in scalars compare by value (NaN equals NaN); other objects by
/// identity.
#[pyfunction]
pub fn has_changed(previous: &Bound<'_, PyAny>, current: &Bound<'_, PyAny>) -> PyResult<bool> {
    // No user equality methods or array comparisons run.
    if previous.is(current) {
        return Ok(false);
    }
    if !previous.get_type().is(current.get_type()) {
        return Ok(true);
    }
    if previous.is_exact_instance_of::<PyFloat>() {
        let a: f64 = previous.extract()?;
        let b: f64 = current.extract()?;
        return Ok(a != b && !(a.is_nan() && b.is_nan()));
    }
    if previous.is_none()
        || previous.is_exact_instance_of::<PyInt>()
        || previous.is_exact_instance_of::<PyBool>()
        || previous.is_exact_instance_of::<PyString>()
        || previous.is_exact_instance_of::<PyBytes>()
        || previous.is_exact_instance_of::<PyComplex>()
    {
        return previous.ne(current);
    }
    Ok(true)
}

/// Call a custom equality with reads untracked, so it cannot add dependencies.
pub(crate) fn call_equal(
    equal: &Bound<'_, PyAny>,
    previous: &Bound<'_, PyAny>,
    current: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let depth = push_frame(None);
    let result = equal.call1((previous, current));
    end_frame(depth)?;
    result?.is_truthy()
}
