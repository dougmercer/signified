//! Effects: the base class of `signified.Effect`, and running an effect.

use std::rc::Rc;

use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use pyo3::PyTraverseError;

use crate::node::{Compute, Kind, Node, Shared};
use crate::refresh;
use crate::scheduler;
use crate::tracking;

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
            node: Shared::new(Kind::Effect),
        }
    }

    fn __init__(slf: &Bound<'_, Self>, r#fn: Py<PyAny>) -> PyResult<()> {
        let node = &slf.get().node;
        let consumer = node.consumer();
        let old = consumer.compute.replace(Some(Compute::Function(r#fn)));
        drop(old);
        consumer.active.set(true);
        consumer.has_run.set(false);
        scheduler::schedule(slf.py(), node)
    }

    /// Schedule a run after dependency invalidation has finished.
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        scheduler::schedule(py, &self.node)
    }

    /// Stop this effect, including any pending run. Safe to repeat.
    fn dispose(&self) {
        self.node.consumer().active.set(false);
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
        self.node.consumer().active.get()
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        self.node.traverse(&visit)
    }

    fn __clear__(&self) {
        self.node.consumer().active.set(false);
        scheduler::discard(&self.node);
        self.node.clear();
    }
}

/// Run one effect if its dependencies changed since its last run.
pub(crate) fn run(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
    let consumer = effect.consumer();
    if consumer.has_run.get() && !refresh::dependencies_changed(py, effect)? {
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
            Compute::Function(f) => f.clone_ref(py),
            Compute::Call { .. } | Compute::Source(_) => {
                unreachable!("an effect runs a zero-argument function")
            }
        });
    let Some(function) = function else {
        return Ok(());
    };
    tracking::start_refresh(effect);
    let depth = tracking::push_frame(Some(effect.clone()));
    let mut result = function.bind(py).call0().map(drop);
    if let Err(error) = tracking::end_frame(depth) {
        result = Err(error);
    }
    if consumer.active.get() {
        // Subscribe to what this run read, even if it raised, so a change to
        // any of it retries the callback.
        tracking::commit_refresh(effect);
    } else {
        tracking::detach_all_deps(effect);
    }
    drop(function);
    result?;
    // Also catches writes after a read during the first run, before the
    // subscriptions existed.
    if consumer.active.get() && refresh::invalidated_since_read(effect) {
        scheduler::schedule(py, effect)?;
    }
    Ok(())
}
