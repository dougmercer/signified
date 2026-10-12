//! Computeds: the base class of `signified.Computed` (and so of `Binding`),
//! `computed_call()`, and reading a computed's value.

use std::rc::Rc;

use pyo3::exceptions::PyAttributeError;
use pyo3::gc::PyVisit;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple, PyType};
use pyo3::PyTraverseError;

use crate::class_getitem;
use crate::hooks::{self, Hook};
use crate::invalidation;
use crate::node::{Compute, Node, RestorePoint, Role, Shared, State};
use crate::refresh;
use crate::runtime;
use crate::subscribe;
use crate::tracking;
use crate::values;

/// Base class of `signified.Computed`: a lazily refreshed derived value.
#[pyclass(
    subclass,
    weakref,
    frozen,
    module = "signified._core",
    name = "Computed"
)]
pub struct ComputedCore {
    pub(crate) node: Shared,
}

pub(crate) fn init_computed(
    obj: &Bound<'_, PyAny>,
    node: &Node,
    compute: Compute,
    equal: Option<Py<PyAny>>,
) -> PyResult<()> {
    let py = obj.py();
    let old = node.computed_state().compute.replace(Some(compute));
    drop(old);
    node.set_equal(py, equal.unwrap_or_else(|| py.None()));
    hooks::call(py, Hook::Created, obj)
}

#[pymethods]
impl ComputedCore {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, PyDict>>) -> Self {
        ComputedCore {
            node: Shared::new(Role::Computed(Default::default())),
        }
    }

    #[pyo3(signature = (f, *, equal = None))]
    fn __init__(slf: &Bound<'_, Self>, f: Py<PyAny>, equal: Option<Py<PyAny>>) -> PyResult<()> {
        init_computed(slf.as_any(), &slf.get().node, Compute::Function(f), equal)
    }

    /// Initialize as a `Binding` over `holder`, a signal holding the source.
    fn _init_source(slf: &Bound<'_, Self>, holder: Py<PyAny>) -> PyResult<()> {
        init_computed(slf.as_any(), &slf.get().node, Compute::Source(holder), None)
    }

    #[classmethod]
    fn __class_getitem__(cls: &Bound<'_, PyType>, item: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        class_getitem(&cls.py().get_type::<ComputedCore>(), cls, item)
    }

    /// The current value, recomputed lazily when a dependency changed. A
    /// cached exception from the last evaluation is raised again.
    #[getter]
    fn value<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        read_computed(slf.py(), &slf.get().node, slf.as_any())
    }

    /// Classes that accept assignment (`Binding`) define `_assign_value`.
    #[setter]
    fn set_value(slf: &Bound<'_, Self>, value: Bound<'_, PyAny>) -> PyResult<()> {
        let py = slf.py();
        let ty = slf.get_type();
        match ty.getattr(intern!(py, "_assign_value")) {
            Ok(assign) => {
                assign.call1((slf, value))?;
                Ok(())
            }
            Err(_) => Err(PyAttributeError::new_err(format!(
                "property 'value' of '{}' object has no setter",
                ty.name()?
            ))),
        }
    }

    #[getter]
    fn _value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        self.node.raw_value(py)
    }

    #[getter]
    fn _version(&self) -> u64 {
        self.node.version.get()
    }

    #[getter]
    fn _equal(&self, py: Python<'_>) -> Py<PyAny> {
        self.node.equal_or_none(py)
    }

    #[setter(_equal)]
    fn set_equal_attr(&self, py: Python<'_>, equal: Py<PyAny>) {
        self.node.set_equal(py, equal);
    }

    #[getter]
    fn _name<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        self.node.name_or_empty(py)
    }

    #[setter(_name)]
    fn set_name_attr(&self, name: Py<PyAny>) {
        self.node.set_name(name);
    }

    /// The reactive values the last evaluation read, in the order they were
    /// first read.
    #[getter]
    fn _deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        tracking::dependency_handles(py, &self.node)
    }

    /// Mark this computed stale and notify its observers.
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        if invalidation::invalidate(self.node.computed_state(), false) {
            invalidation::notify(py, &self.node)?;
        }
        Ok(())
    }

    /// Force a full recomputation on the next read, even if dependency
    /// versions look unchanged.
    fn _invalidate(&self, py: Python<'_>) -> PyResult<()> {
        if !invalidation::invalidate(self.node.computed_state(), true) {
            return Ok(());
        }
        runtime::bump_clock();
        invalidation::notify(py, &self.node)
    }

    /// Notify all observers without marking a change.
    fn _notify(&self, py: Python<'_>) -> PyResult<()> {
        invalidation::notify(py, &self.node)
    }

    /// Subscribe an observer after evaluating, so the observer sees every
    /// later upstream change. The observer is held weakly, and its `update()`
    /// runs after each change, like an effect.
    fn _subscribe(slf: &Bound<'_, Self>, observer: &Bound<'_, PyAny>) -> PyResult<()> {
        let node = &slf.get().node;
        refresh::ensure_uptodate(slf.py(), node, slf.as_any())?;
        subscribe::add_python_observer(node, observer)
    }

    /// Unsubscribe an observer.
    fn _unsubscribe(&self, observer: &Bound<'_, PyAny>) {
        subscribe::remove_python_observer(&self.node, observer);
    }

    fn _observer_count(&self, py: Python<'_>) -> usize {
        subscribe::live_observer_count(py, &self.node)
    }

    /// Whether the current outcome is a fresh value a `Binding` can return to.
    fn _restorable(&self) -> bool {
        let computed = self.node.computed_state();
        computed.state.get() == State::Fresh && computed.error.borrow().is_none()
    }

    /// After `Binding.at()`: return to `value` at `version` on the next
    /// refresh if `holder` still holds `source` at `source_version`.
    fn _arm_restore(
        &self,
        value: Py<PyAny>,
        version: u64,
        holder: &Bound<'_, PyAny>,
        source: &Bound<'_, PyAny>,
        source_version: u64,
    ) -> PyResult<()> {
        let point = RestorePoint {
            value,
            version,
            holder: values::node_of(holder)?,
            source: source.clone().unbind(),
            source_node: values::node_of(source)?,
            source_version,
        };
        let old = self.node.computed_state().restore.replace(Some(point));
        drop(old);
        Ok(())
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        self.node.traverse(&visit)
    }

    fn __clear__(&self) {
        self.node.clear();
    }
}

/// A new `cls` (a `Computed` class) computing `func(*args)`, with each direct
/// reactive argument unwrapped natively on every evaluation. The computation
/// is complete before the `created` hook sees the object.
#[pyfunction]
pub fn computed_call<'py>(
    cls: &Bound<'py, PyType>,
    func: Py<PyAny>,
    args: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyAny>> {
    let obj = cls.call_method1(intern!(cls.py(), "__new__"), (cls,))?;
    let compute = if args.is_empty() {
        Compute::Function(func)
    } else {
        Compute::Call {
            func,
            args: args.iter().map(|arg| arg.unbind()).collect(),
        }
    };
    let node = &obj.cast::<ComputedCore>()?.get().node;
    init_computed(&obj, node, compute, None)?;
    Ok(obj)
}

pub(crate) fn read_computed<'py>(
    py: Python<'py>,
    node: &Rc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    hooks::call(py, Hook::Read, handle)?;
    let refreshed = refresh::ensure_uptodate(py, node, handle);
    // Register the read even when the refresh raises, so the reader retries.
    tracking::track_read(node, handle);
    refreshed?;
    let cached = node.computed_state().error.borrow().as_ref().map(|cached| {
        (
            cached.exception.clone_ref(py),
            cached.traceback.as_ref().map(|tb| tb.clone_ref(py)),
        )
    });
    if let Some((exception, traceback)) = cached {
        let exception = exception.into_bound(py);
        // Reset the traceback so repeated reads do not accumulate frames.
        exception.setattr(intern!(py, "__traceback__"), traceback)?;
        return Err(PyErr::from_value(exception));
    }
    Ok(node.raw_value(py))
}
