//! Effects: the base class of `signified.Effect`. Running one is the
//! engine's (`engine::effect`).

use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use pyo3::PyTraverseError;

use crate::engine::node::Role;
use crate::engine::{scheduler, tracking};
use crate::shared::Shared;

/// Base class of `signified.Effect`: a callback re-run when what it read changes.
#[pyclass(subclass, weakref, frozen, module = "signified._core", name = "Effect")]
pub struct EffectCore {
    pub(crate) node: Shared,
}

#[pymethods]
impl EffectCore {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, PyDict>>) -> Self {
        EffectCore {
            node: Shared::new(Role::Effect(Default::default())),
        }
    }

    fn __init__(slf: &Bound<'_, Self>, r#fn: Py<PyAny>) -> PyResult<()> {
        let node = &slf.get().node;
        let state = node.effect_state();
        let old = state.function.replace(Some(r#fn));
        drop(old);
        state.active.set(true);
        state.has_run.set(false);
        scheduler::schedule(slf.py(), node)
    }

    /// Schedule a run after dependency invalidation has finished.
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        scheduler::schedule(py, &self.node)
    }

    /// Stop this effect, including any pending run. Safe to repeat.
    fn dispose(&self) {
        self.node.effect_state().active.set(false);
        scheduler::discard(&self.node);
        tracking::detach_all_deps(&self.node);
    }

    /// The reactive values the last run read, in the order they were first read.
    #[getter]
    fn _deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        tracking::dependency_handles(py, &self.node)
    }

    #[getter]
    fn _active(&self) -> bool {
        self.node.effect_state().active.get()
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        self.node.traverse(&visit)
    }

    fn __clear__(&self) {
        self.node.effect_state().active.set(false);
        scheduler::discard(&self.node);
        self.node.clear();
    }
}
