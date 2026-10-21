//! Watchers: the base class of `signified.Watcher`. The watching itself is
//! the engine's (`engine::watching`).

use std::rc::Rc;

use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use pyo3::PyTraverseError;

use crate::engine::watching::Watching;
use crate::shared::SharedWatching;
use crate::values;

/// Base class of `signified.Watcher`: reports which watched values have new
/// versions since it was last asked.
#[pyclass(
    subclass,
    weakref,
    frozen,
    module = "signified._core",
    name = "Watcher"
)]
pub struct WatcherCore {
    watching: SharedWatching,
}

#[pymethods]
impl WatcherCore {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, PyDict>>) -> Self {
        WatcherCore {
            watching: SharedWatching(Rc::new(Watching::default())),
        }
    }

    /// Watch `value` (a Signal, Computed or Binding) and report `key` (by
    /// default the value itself) when it changes. A plain value never changes,
    /// so it is not watched.
    #[pyo3(signature = (value, key = None))]
    fn watch(&self, value: &Bound<'_, PyAny>, key: Option<Py<PyAny>>) -> PyResult<()> {
        let Ok(node) = values::node_of(value) else {
            return Ok(());
        };
        let key = key.unwrap_or_else(|| value.clone().unbind());
        self.watching.0.watch(value.py(), &node, value, key)
    }

    /// Stop every watch reported as `key`.
    fn unwatch(&self, key: &Bound<'_, PyAny>) {
        self.watching.0.unwatch(key);
    }

    /// The keys of watched values with a new version since the last call (or
    /// since they were watched), each once.
    fn changed<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, self.watching.0.changed(py))
    }

    fn __len__(&self) -> usize {
        self.watching.0.len()
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        self.watching.0.traverse(&visit)
    }

    fn __clear__(&self) {
        self.watching.0.clear();
    }
}
