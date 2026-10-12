//! Effects: the base class of `signified.Effect`, and running an effect.

use std::rc::Rc;

use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use pyo3::PyTraverseError;

use signified_engine::{scheduler, tracking, Role};

use crate::node::{Node, NodeExt, PyEffect, Shared};

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
            node: Shared::new(Role::effect(PyEffect::default())),
        }
    }

    fn __init__(slf: &Bound<'_, Self>, r#fn: Py<PyAny>) -> PyResult<()> {
        let node = &slf.get().node;
        let state = node.effect_state();
        let old = node.effect_data().function.replace(Some(r#fn));
        drop(old);
        state.active.set(true);
        state.has_run.set(false);
        scheduler::schedule(slf.py(), &node.0)
    }

    /// Schedule a run after dependency invalidation has finished.
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        scheduler::schedule(py, &self.node.0)
    }

    /// Stop this effect, including any pending run. Safe to repeat.
    fn dispose(&self) {
        self.node.effect_state().active.set(false);
        scheduler::discard(&self.node.0);
        tracking::detach_all_deps(&self.node.0);
    }

    /// The reactive values the last run read, in the order they were first read.
    #[getter]
    fn _deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        crate::tracking::dependency_handles(py, &self.node)
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
        scheduler::discard(&self.node.0);
        self.node.clear();
    }
}

/// Run one effect if its dependencies changed since its last run.
pub(crate) fn run(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
    signified_engine::effect::run(
        py,
        effect,
        || {
            effect
                .effect_data()
                .function
                .borrow()
                .as_ref()
                .map(|function| function.clone_ref(py))
        },
        |function| function.bind(py).call0().map(drop),
    )
}
