//! Tracked fields: the data descriptor behind `signified.tracked_fields`, and
//! the base class of the hidden signal it stores.
//!
//! The stored value lives where it would without the descriptor: in the
//! class's slot, or in the instance dict. Until a computation reads the field,
//! that storage holds the plain stored value. The first tracked read replaces
//! it with a hidden source signal (`_FieldSource`, a `Signal` subclass with
//! `FieldSource` as its base) holding the same value. The source records its
//! owner's id: a shallow copy of an instance dict shares the source object,
//! and the copy must not write through it.

use std::rc::Rc;

use pyo3::exceptions::{PyAttributeError, PyTypeError};
use pyo3::ffi;
use pyo3::gc::PyVisit;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString, PyTuple, PyType};
use pyo3::PyTraverseError;

use crate::node::{Node, NodeExt};
use crate::signal::{init_signal, read_signal, write_signal, SignalCore};
use crate::tracking::is_tracking;

/// Base class of the hidden signal that holds one tracked field's value.
#[pyclass(extends = SignalCore, subclass, frozen, module = "signified._core", name = "FieldSource")]
pub struct FieldSource {
    /// `id()` of the instance this source belongs to.
    owner: usize,
}

#[pymethods]
impl FieldSource {
    #[new]
    fn new(_value: &Bound<'_, PyAny>, owner: &Bound<'_, PyAny>) -> PyClassInitializer<Self> {
        PyClassInitializer::from(SignalCore::empty()).add_subclass(FieldSource {
            owner: owner.as_ptr() as usize,
        })
    }

    fn __init__(
        slf: &Bound<'_, Self>,
        value: Bound<'_, PyAny>,
        _owner: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        init_signal(slf.as_super(), value, slf.py().None())
    }
}

fn source_node<'a>(source: &'a Bound<'_, FieldSource>) -> &'a Rc<Node> {
    &source.as_super().get().node
}

/// A slot's member descriptor and its native get and set functions.
struct Slot {
    descr: Py<PyAny>,
    get: ffi::descrgetfunc,
    set: ffi::descrsetfunc,
}

impl Slot {
    fn new(descr: &Bound<'_, PyAny>) -> PyResult<Slot> {
        let ty = descr.get_type();
        let (get, set) = unsafe {
            (
                ffi::PyType_GetSlot(ty.as_type_ptr(), ffi::Py_tp_descr_get),
                ffi::PyType_GetSlot(ty.as_type_ptr(), ffi::Py_tp_descr_set),
            )
        };
        if get.is_null() || set.is_null() {
            return Err(PyErr::take(descr.py()).unwrap_or_else(|| {
                PyTypeError::new_err("tracked field slot must be a data descriptor")
            }));
        }
        Ok(Slot {
            descr: descr.clone().unbind(),
            get: unsafe { std::mem::transmute::<*mut std::ffi::c_void, ffi::descrgetfunc>(get) },
            set: unsafe { std::mem::transmute::<*mut std::ffi::c_void, ffi::descrsetfunc>(set) },
        })
    }
}

/// Data descriptor that tracks reads and reassignment of one attribute.
#[pyclass(frozen, module = "signified._core", name = "TrackedField")]
pub struct TrackedField {
    name: Py<PyString>,
    slot: Option<Slot>,
    default: Option<Py<PyAny>>,
    source_type: Py<PyType>,
}

#[pymethods]
impl TrackedField {
    /// `slot` is the class's member descriptor, or `None` to store the value
    /// in the instance dict. A dict field may give one `default`, returned
    /// while the instance dict has no value. `source_type` is the
    /// `FieldSource` subclass to create on the first tracked read.
    #[new]
    #[pyo3(signature = (name, slot, source_type, *default))]
    fn new(
        name: Py<PyString>,
        slot: Option<&Bound<'_, PyAny>>,
        source_type: Py<PyType>,
        default: &Bound<'_, PyTuple>,
    ) -> PyResult<Self> {
        if default.len() > 1 {
            return Err(PyTypeError::new_err(
                "TrackedField takes at most one default",
            ));
        }
        Ok(TrackedField {
            name,
            slot: slot.map(Slot::new).transpose()?,
            default: default.get_item(0).ok().map(Bound::unbind),
            source_type,
        })
    }

    fn __get__<'py>(
        slf: &Bound<'py, Self>,
        obj: Option<&Bound<'py, PyAny>>,
        _owner: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let Some(obj) = obj else {
            return Ok(slf.clone().into_any());
        };
        let py = slf.py();
        let field = slf.get();
        let stored = field.load(obj)?;
        let Some(source) = field.as_source(&stored) else {
            if !is_tracking() {
                return Ok(stored);
            }
            return field.read_new_source(obj, stored);
        };
        if !is_tracking() {
            return Ok(source_node(source).raw_value(py));
        }
        if source.get().owner == obj.as_ptr() as usize {
            return read_signal(py, source_node(source), source.as_any());
        }
        // A source shared by a copy: this instance gets its own.
        let value = source_node(source).raw_value(py);
        field.read_new_source(obj, value)
    }

    fn __set__(&self, obj: &Bound<'_, PyAny>, value: Bound<'_, PyAny>) -> PyResult<()> {
        let py = obj.py();
        match self.load(obj) {
            Ok(stored) => match self.as_source(&stored) {
                Some(source) if source.get().owner == obj.as_ptr() as usize => {
                    write_signal(py, source_node(source), source.as_any(), value)
                }
                _ => self.store(obj, &value),
            },
            Err(err) if err.is_instance_of::<PyAttributeError>(py) => self.store(obj, &value),
            Err(err) => Err(err),
        }
    }

    fn __delete__(&self, obj: &Bound<'_, PyAny>) -> PyResult<()> {
        Err(PyAttributeError::new_err(format!(
            "tracked field '{}' cannot be deleted",
            self.name.bind(obj.py())
        )))
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.name)?;
        if let Some(slot) = &self.slot {
            visit.call(&slot.descr)?;
        }
        visit.call(&self.default)?;
        visit.call(&self.source_type)
    }
}

impl TrackedField {
    /// `stored` as a source, if it is one.
    fn as_source<'a, 'py>(
        &self,
        stored: &'a Bound<'py, PyAny>,
    ) -> Option<&'a Bound<'py, FieldSource>> {
        if stored.get_type_ptr() != self.source_type.as_ptr().cast() {
            return None;
        }
        stored.cast::<FieldSource>().ok()
    }

    /// Store `value` in a new source owned by `obj`, and read it.
    fn read_new_source<'py>(
        &self,
        obj: &Bound<'py, PyAny>,
        value: Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = obj.py();
        let source = self.source_type.bind(py).call1((value, obj))?;
        self.store(obj, &source)?;
        read_signal(py, source_node(source.cast::<FieldSource>()?), &source)
    }

    /// What the instance's storage holds: a plain value or a source.
    fn load<'py>(&self, obj: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = obj.py();
        if let Some(slot) = &self.slot {
            return unsafe {
                let stored = (slot.get)(slot.descr.as_ptr(), obj.as_ptr(), obj.get_type().as_ptr());
                Bound::from_owned_ptr_or_err(py, stored)
            };
        }
        if let Some(stored) = instance_dict(obj)?.get_item(self.name.bind(py))? {
            return Ok(stored);
        }
        match &self.default {
            Some(default) => Ok(default.bind(py).clone()),
            None => Err(PyAttributeError::new_err(format!(
                "'{}' object has no attribute '{}'",
                obj.get_type().name()?,
                self.name.bind(py)
            ))),
        }
    }

    fn store(&self, obj: &Bound<'_, PyAny>, value: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Some(slot) = &self.slot {
            let status = unsafe { (slot.set)(slot.descr.as_ptr(), obj.as_ptr(), value.as_ptr()) };
            if status < 0 {
                return Err(PyErr::fetch(obj.py()));
            }
            return Ok(());
        }
        instance_dict(obj)?.set_item(self.name.bind(obj.py()), value)
    }
}

fn instance_dict<'py>(obj: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    Ok(obj
        .getattr(intern!(obj.py(), "__dict__"))?
        .cast_into::<PyDict>()?)
}
