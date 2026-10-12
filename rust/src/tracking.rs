//! Dependency tracking for Python: `untracked()`, `is_tracking()`, and the
//! engine's tracking steps specialized to the Python host.

use std::rc::Rc;

use pyo3::prelude::*;
use pyo3::types::PyTuple;
use signified_engine::{tracking, EngineError, Host};

use crate::host::PyHost;
use crate::node::Node;

/// Push a tracking frame and return the depth to pass to `end_frame`.
#[inline]
pub(crate) fn push_frame(frame: Option<Rc<Node>>) -> usize {
    tracking::push_frame(frame)
}

/// Remove the frame that `push_frame` returned `depth` for.
#[inline]
pub(crate) fn end_frame(depth: usize) -> PyResult<()> {
    tracking::end_frame::<PyHost>(depth)
}

/// Register a read of `node` (whose Python object is `handle`) with the
/// consumer that is running, if any.
#[inline]
pub(crate) fn track_read(node: &Rc<Node>, handle: &Bound<'_, PyAny>) {
    tracking::track_read(node, || handle.clone().unbind())
}

/// Whether a reactive read right now would register a dependency.
#[pyfunction]
pub fn is_tracking() -> bool {
    tracking::is_tracking::<PyHost>()
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
        push_frame(None);
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&self, _exc: &Bound<'_, PyTuple>) -> PyResult<bool> {
        // Check before popping, so a mismatch cannot remove a computation's frame.
        if !tracking::in_untracked_block::<PyHost>() {
            return Err(PyHost::engine_error(EngineError::UntrackedExitWithoutEnter));
        }
        drop(tracking::pop_frame::<PyHost>());
        Ok(false)
    }
}

/// The Python objects of a consumer's current dependencies, in the order
/// they were first read.
pub(crate) fn dependency_handles<'py>(
    py: Python<'py>,
    node: &Node,
) -> PyResult<Bound<'py, PyTuple>> {
    let handles: Vec<Py<PyAny>> = node
        .reader_state()
        .deps()
        .iter()
        .map(|link| link.handle.clone_ref(py))
        .collect();
    PyTuple::new(py, handles)
}
