//! The base classes Python sees: `Signal`, `Computed` and `Effect`, plus the
//! module-level functions. `signified/_reactive.py` subclasses these together
//! with the operator mixin to build the public classes.

use std::rc::Rc;

use pyo3::exceptions::{PyAttributeError, PyRuntimeError};
use pyo3::gc::PyVisit;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString, PySuper, PyTuple, PyType};
use pyo3::PyTraverseError;

use crate::config;
use crate::effects;
use crate::graph::{self, rt, Compute, Kind, Node, RestorePoint, Shared, State};

/// `cls[item]` on the base class itself, and the next `__class_getitem__` in
/// the MRO (`typing.Generic`'s) for the public subclasses.
fn class_getitem(
    base: &Bound<'_, PyType>,
    cls: &Bound<'_, PyType>,
    item: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let py = cls.py();
    if cls.is(base) {
        let alias = py
            .import(intern!(py, "types"))?
            .getattr(intern!(py, "GenericAlias"))?
            .call1((cls, item))?;
        return Ok(alias.unbind());
    }
    let next = PySuper::new(base, cls)?.getattr(intern!(py, "__class_getitem__"))?;
    Ok(next.call1((item,))?.unbind())
}

fn new_node(kind: Kind) -> Shared {
    Shared(Rc::new(Node::new(kind)))
}

fn name_of<'py>(py: Python<'py>, node: &Node) -> Bound<'py, PyAny> {
    match node.name.borrow().as_ref() {
        Some(name) => name.bind(py).clone(),
        None => PyString::new(py, "").into_any(),
    }
}

fn set_name(node: &Node, name: Py<PyAny>) {
    let old = node.name.replace(Some(name));
    drop(old);
}

fn equal_of(py: Python<'_>, node: &Node) -> Py<PyAny> {
    match node.equal.borrow().as_ref() {
        Some(equal) => equal.clone_ref(py),
        None => py.None(),
    }
}

fn set_equal(py: Python<'_>, node: &Node, equal: Py<PyAny>) {
    let equal = if equal.is_none(py) { None } else { Some(equal) };
    let old = node.equal.replace(equal);
    drop(old);
}

fn generic_setattr(
    obj: &Bound<'_, PyAny>,
    name: &Bound<'_, PyString>,
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<()> {
    let value = value.map_or(std::ptr::null_mut(), |value| value.as_ptr());
    let status = unsafe { pyo3::ffi::PyObject_GenericSetAttr(obj.as_ptr(), name.as_ptr(), value) };
    if status < 0 {
        return Err(PyErr::fetch(obj.py()));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Signal
// ---------------------------------------------------------------------------

/// Base class of `signified.Signal`: mutable state.
#[pyclass(subclass, weakref, frozen, module = "signified._core", name = "Signal")]
pub struct SignalCore {
    pub(crate) node: Shared,
}

#[pymethods]
impl SignalCore {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, PyDict>>) -> Self {
        SignalCore {
            node: new_node(Kind::Signal),
        }
    }

    #[pyo3(signature = (value, *, equal = None))]
    fn __init__(
        slf: &Bound<'_, Self>,
        value: Bound<'_, PyAny>,
        equal: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        let py = slf.py();
        config::warn_signal_value(py, slf.as_any(), &value)?;
        let node = &slf.get().node;
        let old = node.value.replace(Some(value.unbind()));
        drop(old);
        set_equal(py, node, equal.unwrap_or_else(|| py.None()));
        config::hook(py, intern!(py, "created"), slf.as_any())
    }

    #[classmethod]
    fn __class_getitem__(cls: &Bound<'_, PyType>, item: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        class_getitem(&cls.py().get_type::<SignalCore>(), cls, item)
    }

    /// The current value. Reading it inside a computation or effect makes it a
    /// dependency; assigning a changed value notifies observers.
    #[getter]
    fn value<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        graph::read_signal(slf.py(), &slf.get().node, slf.as_any())
    }

    #[setter]
    fn set_value(slf: &Bound<'_, Self>, value: Bound<'_, PyAny>) -> PyResult<()> {
        graph::write_signal(slf.py(), &slf.get().node, slf.as_any(), value)
    }

    /// The stored value, without tracking a read.
    #[getter]
    fn _value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        graph::raw_value(py, &self.node)
    }

    #[getter]
    fn _version(&self) -> u64 {
        self.node.version.get()
    }

    #[getter]
    fn _equal(&self, py: Python<'_>) -> Py<PyAny> {
        equal_of(py, &self.node)
    }

    #[setter(_equal)]
    fn set_equal_attr(&self, py: Python<'_>, equal: Py<PyAny>) {
        set_equal(py, &self.node, equal);
    }

    #[getter]
    fn _name<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        name_of(py, &self.node)
    }

    #[setter(_name)]
    fn set_name_attr(&self, name: Py<PyAny>) {
        set_name(&self.node, name);
    }

    /// Notify all observers unconditionally.
    ///
    /// Unlike assigning to `.value`, this does not check whether the stored
    /// value changed. Use it after mutating the stored object in place.
    fn update(slf: &Bound<'_, Self>) -> PyResult<()> {
        graph::update_signal(slf.py(), &slf.get().node, slf.as_any())
    }

    /// Force downstream recomputation; for a Signal, the same as `update()`.
    fn invalidate(slf: &Bound<'_, Self>) -> PyResult<()> {
        graph::update_signal(slf.py(), &slf.get().node, slf.as_any())
    }

    /// Notify all observers without marking a change.
    fn notify(&self, py: Python<'_>) -> PyResult<()> {
        graph::notify(py, &self.node)
    }

    /// Subscribe an observer (any object with an `update()` method). It is
    /// held weakly, and its `update()` runs after each change, like an effect.
    fn subscribe(&self, observer: &Bound<'_, PyAny>) -> PyResult<()> {
        graph::add_python_observer(&self.node, observer)
    }

    /// Unsubscribe an observer.
    fn unsubscribe(&self, observer: &Bound<'_, PyAny>) {
        graph::remove_python_observer(&self.node, observer);
    }

    fn _observer_count(&self, py: Python<'_>) -> usize {
        graph::live_observer_count(py, &self.node)
    }

    /// Return to an earlier value and version and notify observers.
    fn _restore(slf: &Bound<'_, Self>, value: Bound<'_, PyAny>, version: u64) -> PyResult<()> {
        graph::restore_signal(slf.py(), &slf.get().node, slf.as_any(), value, version)
    }

    /// Assign `value`, private names and class attributes on the signal;
    /// forward any other attribute write to the wrapped object, then notify.
    fn __setattr__(
        slf: &Bound<'_, Self>,
        name: &Bound<'_, PyString>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let py = slf.py();
        if name.is(intern!(py, "value")) {
            return generic_setattr(slf.as_any(), name, Some(value));
        }
        let text = name.to_str()?;
        if text == "value" || text.starts_with('_') || slf.get_type().hasattr(name)? {
            return generic_setattr(slf.as_any(), name, Some(value));
        }
        let node = &slf.get().node;
        let wrapped = graph::raw_value(py, node);
        if !wrapped.hasattr(name)? {
            return Err(PyAttributeError::new_err(format!(
                "'{}' object has no attribute '{}'",
                wrapped.get_type().name()?,
                text
            )));
        }
        wrapped.setattr(name, value)?;
        graph::update_signal(py, node, slf.as_any())
    }

    fn __delattr__(slf: &Bound<'_, Self>, name: &Bound<'_, PyString>) -> PyResult<()> {
        generic_setattr(slf.as_any(), name, None)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        self.node.traverse(&visit)
    }

    fn __clear__(&self) {
        self.node.clear();
    }
}

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

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

fn init_computed(
    obj: &Bound<'_, PyAny>,
    node: &Node,
    compute: Compute,
    equal: Option<Py<PyAny>>,
) -> PyResult<()> {
    let py = obj.py();
    let old = node.consumer().compute.replace(Some(compute));
    drop(old);
    set_equal(py, node, equal.unwrap_or_else(|| py.None()));
    config::hook(py, intern!(py, "created"), obj)
}

#[pymethods]
impl ComputedCore {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, PyDict>>) -> Self {
        ComputedCore {
            node: new_node(Kind::Computed),
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
        graph::read_computed(slf.py(), &slf.get().node, slf.as_any())
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
        graph::raw_value(py, &self.node)
    }

    #[getter]
    fn _version(&self) -> u64 {
        self.node.version.get()
    }

    #[getter]
    fn _equal(&self, py: Python<'_>) -> Py<PyAny> {
        equal_of(py, &self.node)
    }

    #[setter(_equal)]
    fn set_equal_attr(&self, py: Python<'_>, equal: Py<PyAny>) {
        set_equal(py, &self.node, equal);
    }

    #[getter]
    fn _name<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        name_of(py, &self.node)
    }

    #[setter(_name)]
    fn set_name_attr(&self, name: Py<PyAny>) {
        set_name(&self.node, name);
    }

    /// The reactive values the last evaluation read, in the order they were
    /// first read.
    #[getter]
    fn _deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        graph::dependency_handles(py, &self.node)
    }

    /// Mark this computed stale and notify its observers.
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        if graph::invalidate(&self.node, false) {
            graph::notify(py, &self.node)?;
        }
        Ok(())
    }

    /// Force a full recomputation on the next read, even if dependency
    /// versions look unchanged.
    fn _invalidate(&self, py: Python<'_>) -> PyResult<()> {
        if !graph::invalidate(&self.node, true) {
            return Ok(());
        }
        graph::bump_clock();
        graph::notify(py, &self.node)
    }

    /// Notify all observers without marking a change.
    fn notify(&self, py: Python<'_>) -> PyResult<()> {
        graph::notify(py, &self.node)
    }

    /// Subscribe an observer after evaluating, so the observer sees every
    /// later upstream change. The observer is held weakly, and its `update()`
    /// runs after each change, like an effect.
    fn subscribe(slf: &Bound<'_, Self>, observer: &Bound<'_, PyAny>) -> PyResult<()> {
        let node = &slf.get().node;
        graph::ensure_uptodate(slf.py(), node, slf.as_any())?;
        graph::add_python_observer(node, observer)
    }

    /// Unsubscribe an observer.
    fn unsubscribe(&self, observer: &Bound<'_, PyAny>) {
        graph::remove_python_observer(&self.node, observer);
    }

    fn _observer_count(&self, py: Python<'_>) -> usize {
        graph::live_observer_count(py, &self.node)
    }

    /// Whether the current outcome is a fresh value a `Binding` can return to.
    fn _restorable(&self) -> bool {
        let consumer = self.node.consumer();
        consumer.state.get() == State::Fresh && consumer.error.borrow().is_none()
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
            holder: graph::node_of(holder)?,
            source: source.clone().unbind(),
            source_node: graph::node_of(source)?,
            source_version,
        };
        let old = self.node.consumer().restore.replace(Some(point));
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

// ---------------------------------------------------------------------------
// Effect
// ---------------------------------------------------------------------------

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
            node: new_node(Kind::Effect),
        }
    }

    fn __init__(slf: &Bound<'_, Self>, r#fn: Py<PyAny>) -> PyResult<()> {
        let node = &slf.get().node;
        let consumer = node.consumer();
        let old = consumer.compute.replace(Some(Compute::Function(r#fn)));
        drop(old);
        consumer.active.set(true);
        consumer.has_run.set(false);
        effects::schedule(slf.py(), node)
    }

    /// Schedule a run after dependency invalidation has finished.
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        effects::schedule(py, &self.node)
    }

    /// Stop this effect, including any pending run. Safe to repeat.
    fn dispose(&self) {
        self.node.consumer().active.set(false);
        effects::discard(&self.node);
        graph::detach_all_deps(&self.node);
    }

    /// The reactive values the last run read, in the order they were first read.
    #[getter]
    fn _deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        graph::dependency_handles(py, &self.node)
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
        effects::discard(&self.node);
        self.node.clear();
    }
}

// ---------------------------------------------------------------------------
// Module functions
// ---------------------------------------------------------------------------

/// Start a block whose reads do not subscribe the enclosing computation.
#[pyfunction]
pub fn push_untracked() {
    graph::push_frame(None);
}

#[pyfunction]
pub fn pop_untracked() -> PyResult<()> {
    // Check before popping, so a mismatch cannot remove a computation's frame.
    if !graph::in_untracked_block() {
        return Err(PyRuntimeError::new_err(
            "pop_untracked() without a matching push_untracked()",
        ));
    }
    graph::pop_frame();
    Ok(())
}

/// Whether a reactive read right now would register a dependency.
#[pyfunction]
pub fn is_tracking() -> bool {
    graph::is_tracking()
}

/// Exact built-in scalars compare by value (NaN equals NaN); other objects by
/// identity.
#[pyfunction]
pub fn has_changed(previous: &Bound<'_, PyAny>, current: &Bound<'_, PyAny>) -> PyResult<bool> {
    graph::has_changed(previous, current)
}

/// `cls(func)`, computing `func(*args)` with each direct reactive argument
/// unwrapped natively on every evaluation.
#[pyfunction]
pub fn computed_call<'py>(
    cls: &Bound<'py, PyType>,
    func: Py<PyAny>,
    args: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyAny>> {
    let obj = cls.call1((func.clone_ref(cls.py()),))?;
    if !args.is_empty() {
        let node = &obj.cast::<ComputedCore>()?.get().node;
        let call = Compute::Call {
            func,
            args: args.iter().map(|arg| arg.unbind()).collect(),
        };
        let old = node.consumer().compute.replace(Some(call));
        drop(old);
    }
    Ok(obj)
}

#[pyfunction]
pub fn begin_batch() {
    let rt = rt();
    rt.batch_depth.set(rt.batch_depth.get() + 1);
}

#[pyfunction]
pub fn end_batch() {
    let rt = rt();
    rt.batch_depth.set(rt.batch_depth.get().saturating_sub(1));
}

/// Run pending effects unless a batch, walk or flush is in progress.
#[pyfunction]
pub fn flush(py: Python<'_>) -> PyResult<()> {
    effects::flush(py)
}

/// Register classes whose `value` is the engine's own getter, so operators
/// read their instances natively.
#[pyfunction]
pub fn _register_standard_types(types: Vec<Bound<'_, PyType>>) {
    for ty in types {
        graph::register_standard_type(ty.into_any().unbind());
    }
}

/// Unwrap exactly one reactive boundary: a Signal, Computed or Binding gives
/// its value (a dependency read, inside a computation); anything else is
/// returned unchanged.
#[pyfunction]
pub fn unref<'py>(py: Python<'py>, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    graph::resolve_arg(py, value)
}

/// Whether `obj` is a reactive value (a Signal, Computed or Binding).
#[pyfunction]
pub fn is_reactive(obj: &Bound<'_, PyAny>) -> bool {
    graph::is_reactive(obj)
}

// ---------------------------------------------------------------------------
// Context managers
// ---------------------------------------------------------------------------

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
        graph::push_frame(None);
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&self, _exc: &Bound<'_, PyTuple>) -> PyResult<bool> {
        pop_untracked()?;
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
        begin_batch();
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: &Bound<'_, PyAny>,
        exc: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        end_batch();
        let flushed = effects::flush(py);
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

/// `with signal.at(value):` holds `value` inside the block, then returns to
/// the previous value and, if nothing else wrote the signal, the previous
/// version.
/// The value and version before a `Signal.at()` block, and the version on entry.
type SavedState = Option<(Py<PyAny>, u64, u64)>;

#[pyclass(frozen, module = "signified._core", name = "SignalAt")]
pub struct SignalAt {
    signal: Py<PyAny>,
    value: Py<PyAny>,
    /// The value and version before the block, and the version on entry.
    saved: std::sync::Mutex<SavedState>,
}

impl SignalAt {
    fn saved(&self) -> PyResult<std::sync::MutexGuard<'_, SavedState>> {
        self.saved
            .lock()
            .map_err(|_| PyRuntimeError::new_err("Signal.at() context is broken"))
    }
}

#[pymethods]
impl SignalAt {
    #[new]
    fn new(signal: Py<PyAny>, value: Py<PyAny>) -> Self {
        SignalAt {
            signal,
            value,
            saved: std::sync::Mutex::new(None),
        }
    }

    fn __enter__(&self, py: Python<'_>) -> PyResult<()> {
        let signal = self.signal.bind(py);
        let node = graph::node_of(signal)?;
        let before = graph::raw_value(py, &node).unbind();
        let before_version = node.version.get();
        signal.setattr(intern!(py, "value"), self.value.bind(py))?;
        let entered_version = node.version.get();
        let old = self
            .saved()?
            .replace((before, before_version, entered_version));
        drop(old);
        Ok(())
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&self, py: Python<'_>, _exc: &Bound<'_, PyTuple>) -> PyResult<bool> {
        let saved = self.saved()?.take();
        let Some((before, before_version, entered_version)) = saved else {
            return Ok(false);
        };
        let signal = self.signal.bind(py);
        let node = graph::node_of(signal)?;
        if node.version.get() != entered_version {
            // Written again inside the block: an ordinary assignment.
            signal.setattr(intern!(py, "value"), before)?;
        } else if entered_version != before_version {
            // Versions are never reused, so `before_version` still names
            // exactly `before`.
            graph::restore_signal(py, &node, signal, before.into_bound(py), before_version)?;
        }
        Ok(false)
    }
}
