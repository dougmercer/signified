//! Signals: the base class of `signified.Signal`, reading and writing a
//! signal's value, and the `Signal.at()` context.

use std::rc::Rc;

use pyo3::exceptions::{PyAttributeError, PyRuntimeError};
use pyo3::gc::PyVisit;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString, PyTuple, PyType};
use pyo3::PyTraverseError;

use crate::class_getitem;
use crate::hooks::{self, Hook};
use crate::invalidation;
use crate::node::{Node, Role, Shared};
use crate::runtime::{bump_clock, bump_version};
use crate::subscribe;
use crate::tracking::track_read;
use crate::values::{self, call_equal, has_changed};

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
        SignalCore::empty()
    }

    #[pyo3(signature = (value, *, equal = None))]
    fn __init__(
        slf: &Bound<'_, Self>,
        value: Bound<'_, PyAny>,
        equal: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        init_signal(slf, value, equal.unwrap_or_else(|| slf.py().None()))
    }

    #[classmethod]
    fn __class_getitem__(cls: &Bound<'_, PyType>, item: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        class_getitem(&cls.py().get_type::<SignalCore>(), cls, item)
    }

    /// The current value. Reading it inside a computation or effect makes it a
    /// dependency; assigning a changed value notifies observers.
    #[getter]
    fn value<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        read_signal(slf.py(), &slf.get().node, slf.as_any())
    }

    #[setter]
    fn set_value(slf: &Bound<'_, Self>, value: Bound<'_, PyAny>) -> PyResult<()> {
        write_signal(slf.py(), &slf.get().node, slf.as_any(), value)
    }

    /// The stored value, without tracking a read.
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

    /// Notify all observers unconditionally.
    ///
    /// Unlike assigning to `.value`, this does not check whether the stored
    /// value changed. Use it after mutating the stored object in place.
    fn update(slf: &Bound<'_, Self>) -> PyResult<()> {
        update_signal(slf.py(), &slf.get().node, slf.as_any())
    }

    /// Force downstream recomputation; for a Signal, the same as `update()`.
    fn invalidate(slf: &Bound<'_, Self>) -> PyResult<()> {
        update_signal(slf.py(), &slf.get().node, slf.as_any())
    }

    /// Notify all observers without marking a change.
    fn _notify(&self, py: Python<'_>) -> PyResult<()> {
        invalidation::notify(py, &self.node)
    }

    /// Subscribe an observer (any object with an `update()` method). It is
    /// held weakly, and its `update()` runs after each change, like an effect.
    fn _subscribe(&self, observer: &Bound<'_, PyAny>) -> PyResult<()> {
        subscribe::add_python_observer(&self.node, observer)
    }

    /// Unsubscribe an observer.
    fn _unsubscribe(&self, observer: &Bound<'_, PyAny>) {
        subscribe::remove_python_observer(&self.node, observer);
    }

    fn _observer_count(&self, py: Python<'_>) -> usize {
        subscribe::live_observer_count(py, &self.node)
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
        let wrapped = node.raw_value(py);
        if !wrapped.hasattr(name)? {
            return Err(PyAttributeError::new_err(format!(
                "'{}' object has no attribute '{}'",
                wrapped.get_type().name()?,
                text
            )));
        }
        wrapped.setattr(name, value)?;
        update_signal(py, node, slf.as_any())
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

impl SignalCore {
    /// A signal with no value yet; `init_signal` gives it one.
    pub(crate) fn empty() -> Self {
        SignalCore {
            node: Shared::new(Role::Signal),
        }
    }
}

/// Store a new signal's first value and equality, then report its creation.
pub(crate) fn init_signal(
    slf: &Bound<'_, SignalCore>,
    value: Bound<'_, PyAny>,
    equal: Py<PyAny>,
) -> PyResult<()> {
    let py = slf.py();
    let node = &slf.get().node;
    let old = node.value.replace(Some(value.unbind()));
    drop(old);
    node.set_equal(py, equal);
    hooks::call(py, Hook::Created, slf.as_any())
}

fn uninitialized() -> PyErr {
    PyRuntimeError::new_err("Signal.__init__() was not called")
}

pub(crate) fn read_signal<'py>(
    py: Python<'py>,
    node: &Rc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    // The hook runs first and may write this signal; the value and the
    // version the read registers are both taken after it.
    hooks::call(py, Hook::Read, handle)?;
    let value = match node.value.borrow().as_ref() {
        Some(value) => value.bind(py).clone(),
        None => return Err(uninitialized()),
    };
    track_read(node, handle);
    Ok(value)
}

/// Assign a signal's value; observers hear about it only if it changed.
pub(crate) fn write_signal(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
) -> PyResult<()> {
    let old = node.value.borrow().as_ref().map(|old| old.clone_ref(py));
    let Some(old) = old else {
        return Err(uninitialized());
    };
    if !has_changed(old.bind(py), &value)? {
        return Ok(());
    }
    let equal = node
        .equal
        .borrow()
        .as_ref()
        .map(|equal| equal.clone_ref(py));
    if let Some(equal) = equal {
        if call_equal(equal.bind(py), old.bind(py), &value)? {
            return Ok(());
        }
    }
    let previous = node.value.replace(Some(value.unbind()));
    bump_version(node);
    drop(previous);
    drop(old);
    hooks::call(py, Hook::Updated, handle)?;
    invalidation::notify(py, node)
}

/// Notify a signal's observers unconditionally (after an in-place mutation).
fn update_signal(py: Python<'_>, node: &Rc<Node>, handle: &Bound<'_, PyAny>) -> PyResult<()> {
    bump_version(node);
    hooks::call(py, Hook::Updated, handle)?;
    invalidation::notify(py, node)
}

/// Return a signal to an earlier value and version (the end of `Signal.at`).
/// The clock still advances, so a consumer that refreshed in the meantime
/// cannot take the unchanged-graph fast path.
fn restore_signal(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
    version: u64,
) -> PyResult<()> {
    let previous = node.value.replace(Some(value.unbind()));
    node.version.set(version);
    bump_clock();
    drop(previous);
    hooks::call(py, Hook::Updated, handle)?;
    invalidation::notify(py, node)
}

/// The state of a `Signal.at()` context: the signal, the temporary value,
/// whether a block is using the context, and, once entered, the value and
/// version before the block and the version on entry.
struct AtState {
    signal: Option<Py<PyAny>>,
    value: Option<Py<PyAny>>,
    active: bool,
    saved: Option<(Py<PyAny>, u64, u64)>,
}

/// `with signal.at(value):` holds `value` inside the block, then returns to
/// the previous value and, if nothing else wrote the signal, the previous
/// version.
#[pyclass(frozen, module = "signified._core", name = "SignalAt")]
pub struct SignalAt {
    // Never locked across a call into Python.
    state: std::sync::Mutex<AtState>,
}

impl SignalAt {
    fn state(&self) -> PyResult<std::sync::MutexGuard<'_, AtState>> {
        self.state
            .lock()
            .map_err(|_| PyRuntimeError::new_err("Signal.at() context is broken"))
    }

    /// Assign the temporary value and record what to return to. If the
    /// assignment raises after changing the value (an effect or hook
    /// failed), the previous value is assigned back before the error
    /// propagates, as a `finally` block would.
    fn enter(&self, py: Python<'_>, signal: &Bound<'_, PyAny>, value: Py<PyAny>) -> PyResult<()> {
        let node = values::node_of(signal)?;
        let before = node.raw_value(py).unbind();
        let before_version = node.version.get();
        if let Err(error) = signal.setattr(intern!(py, "value"), value) {
            if node.version.get() == before_version {
                return Err(error);
            }
            return match signal.setattr(intern!(py, "value"), before) {
                Ok(()) => Err(error),
                Err(restore_error) => {
                    let context = error.into_value(py);
                    restore_error
                        .value(py)
                        .setattr(intern!(py, "__context__"), context)?;
                    Err(restore_error)
                }
            };
        }
        let entered_version = node.version.get();
        let old = self
            .state()?
            .saved
            .replace((before, before_version, entered_version));
        drop(old);
        Ok(())
    }
}

#[pymethods]
impl SignalAt {
    #[new]
    fn new(signal: Py<PyAny>, value: Py<PyAny>) -> Self {
        SignalAt {
            state: std::sync::Mutex::new(AtState {
                signal: Some(signal),
                value: Some(value),
                active: false,
                saved: None,
            }),
        }
    }

    fn __enter__(&self, py: Python<'_>) -> PyResult<()> {
        let (signal, value) = {
            let mut state = self.state()?;
            if state.active {
                return Err(PyRuntimeError::new_err(
                    "Signal.at() context is already active",
                ));
            }
            let pair = match (&state.signal, &state.value) {
                (Some(signal), Some(value)) => (signal.clone_ref(py), value.clone_ref(py)),
                _ => return Err(PyRuntimeError::new_err("Signal.at() context was cleared")),
            };
            state.active = true;
            pair
        };
        let entered = self.enter(py, signal.bind(py), value);
        if entered.is_err() {
            self.state()?.active = false;
        }
        entered
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&self, py: Python<'_>, _exc: &Bound<'_, PyTuple>) -> PyResult<bool> {
        let (signal, saved) = {
            let mut state = self.state()?;
            state.active = false;
            let saved = state.saved.take();
            (
                state.signal.as_ref().map(|signal| signal.clone_ref(py)),
                saved,
            )
        };
        let (Some(signal), Some((before, before_version, entered_version))) = (signal, saved)
        else {
            return Ok(false);
        };
        let signal = signal.bind(py);
        let node = values::node_of(signal)?;
        if node.version.get() != entered_version {
            // Written again inside the block: an ordinary assignment.
            signal.setattr(intern!(py, "value"), before)?;
        } else if entered_version != before_version {
            // Versions are never reused, so `before_version` still names
            // exactly `before`.
            restore_signal(py, &node, signal, before.into_bound(py), before_version)?;
        }
        Ok(false)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        // A busy lock is skipped, like a busy cell in a node.
        if let Ok(state) = self.state.try_lock() {
            for object in [&state.signal, &state.value].into_iter().flatten() {
                visit.call(object)?;
            }
            if let Some((before, ..)) = &state.saved {
                visit.call(before)?;
            }
        }
        Ok(())
    }

    fn __clear__(&self) {
        let taken = self
            .state
            .lock()
            .ok()
            .map(|mut state| (state.signal.take(), state.value.take(), state.saved.take()));
        drop(taken);
    }
}
