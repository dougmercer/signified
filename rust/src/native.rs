//! Computeds whose values come from native code in other extension modules, and the C API
//! (`signified._core._C_API`, described by the `signified-api` crate) that creates them.
//!
//! A native computed is an ordinary computed node with `Compute::Native`: its arguments are
//! resolved and tracked like `computed_call`'s, and its kernel runs instead of a Python callable.

use std::ffi::c_void;
use std::ptr::null_mut;
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};

use pyo3::exceptions::PyTypeError;
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyFloat, PyTuple, PyType};
use signified_api::{CApi, Kernel, Object, CAPSULE_NAME, VERSION};

use crate::computed::{init_computed, ComputedCore};
use crate::node::Compute;
use crate::values::unref;

/// A kernel owned by a computed; its context is released when the last copy is dropped.
pub(crate) struct NativeKernel(Kernel);

impl Drop for NativeKernel {
    fn drop(&mut self) {
        if let Some(release) = self.0.release {
            // SAFETY: the kernel's owner promised `release` frees `ctx`, once, with the GIL held;
            // nodes are only dropped while attached (see `Shared`).
            unsafe { release(self.0.ctx) };
        }
    }
}

/// Evaluate *kernel* over *args* (reactive ones resolved and tracked), given the node's
/// current value *previous*.
pub(crate) fn run(
    py: Python<'_>,
    kernel: &NativeKernel,
    args: &[Py<PyAny>],
    previous: Option<&Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    let mut resolved = Vec::with_capacity(args.len());
    for arg in args {
        resolved.push(unref(py, arg.bind(py))?);
    }
    let pointers: Vec<Object> = resolved
        .iter()
        .map(|value| value.as_ptr() as Object)
        .collect();
    let previous = previous.map_or(null_mut(), |value| value.as_ptr() as Object);
    // SAFETY: the pointers are live borrowed references for the duration of the call; the
    // kernel returns a new reference or null with an exception set.
    let result = unsafe {
        (kernel.0.call)(
            kernel.0.ctx,
            pointers.as_ptr(),
            pointers.len() as isize,
            previous,
        )
    };
    unsafe { Bound::from_owned_ptr_or_err(py, result as *mut ffi::PyObject) }.map(Bound::unbind)
}

fn new_native_computed<'py>(
    py: Python<'py>,
    cls: &Bound<'py, PyAny>,
    kernel: NativeKernel,
    args: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let cls = cls.cast::<PyType>()?;
    if !cls.is_subclass_of::<ComputedCore>()? {
        return Err(PyTypeError::new_err(
            "native computeds must be instances of a Computed class",
        ));
    }
    let args = args.cast::<PyTuple>()?;
    let obj = cls.call_method1(intern!(py, "__new__"), (cls,))?;
    let node = &obj.cast::<ComputedCore>()?.get().node;
    let compute = Compute::Native {
        kernel: Rc::new(kernel),
        args: args.iter().map(|arg| arg.unbind()).collect(),
    };
    init_computed(&obj, node, compute, None)?;
    Ok(obj)
}

unsafe extern "C" fn api_new_computed(cls: Object, kernel: Kernel, args: Object) -> Object {
    // Owned from here, so it is released however this ends.
    let kernel = NativeKernel(kernel);
    Python::attach(|py| {
        if cls.is_null() || args.is_null() {
            PyTypeError::new_err("new_computed needs a class and an argument tuple").restore(py);
            return null_mut();
        }
        // SAFETY: the caller passes borrowed references to live objects.
        let cls = unsafe { Bound::from_borrowed_ptr(py, cls as *mut ffi::PyObject) };
        let args = unsafe { Bound::from_borrowed_ptr(py, args as *mut ffi::PyObject) };
        match new_native_computed(py, &cls, kernel, &args) {
            Ok(obj) => obj.into_ptr() as Object,
            Err(error) => {
                error.restore(py);
                null_mut()
            }
        }
    })
}

/// What the capsule points to.
static API: CApi = CApi {
    version: VERSION,
    size: std::mem::size_of::<CApi>() as u32,
    new_computed: api_new_computed,
};

/// Add the `_C_API` capsule to the module.
pub(crate) fn add_capsule(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    // SAFETY: the table is static and the name a static C string, as the capsule requires.
    let capsule = unsafe {
        ffi::PyCapsule_New(
            &API as *const CApi as *mut c_void,
            CAPSULE_NAME.as_ptr(),
            None,
        )
    };
    let capsule = unsafe { Bound::from_owned_ptr_or_err(py, capsule) }?;
    module.add("_C_API", capsule)
}

// A kernel for tests: the sum of its float arguments, through the C API like another extension.
// Its context is a boxed marker, so releases can be counted.

static TEST_CALLS: AtomicUsize = AtomicUsize::new(0);
static TEST_RELEASES: AtomicUsize = AtomicUsize::new(0);

unsafe extern "C" fn test_sum(
    _ctx: *mut c_void,
    args: *const Object,
    nargs: isize,
    previous: Object,
) -> Object {
    Python::attach(|py| {
        TEST_CALLS.fetch_add(1, Ordering::Relaxed);
        let mut total = 0.0;
        for index in 0..nargs as usize {
            let arg =
                unsafe { Bound::from_borrowed_ptr(py, *args.add(index) as *mut ffi::PyObject) };
            match arg.extract::<f64>() {
                Ok(value) => total += value,
                Err(error) => {
                    error.restore(py);
                    return null_mut();
                }
            }
        }
        if !previous.is_null() {
            let previous = unsafe { Bound::from_borrowed_ptr(py, previous as *mut ffi::PyObject) };
            if previous.extract::<f64>().is_ok_and(|value| value == total) {
                return previous.into_ptr() as Object;
            }
        }
        PyFloat::new(py, total).into_ptr() as Object
    })
}

unsafe extern "C" fn test_release(ctx: *mut c_void) {
    drop(unsafe { Box::from_raw(ctx as *mut u8) });
    TEST_RELEASES.fetch_add(1, Ordering::Relaxed);
}

/// A `cls` computing the sum of *args* natively, made through the C API (for tests); a sum equal
/// to the previous one is reported unchanged.
#[pyfunction]
#[pyo3(signature = (cls, *args))]
pub fn _native_test_sum<'py>(
    cls: &Bound<'py, PyAny>,
    args: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyAny>> {
    let py = cls.py();
    // Through the capsule, as another extension gets the table.
    // SAFETY: attached; the capsule's pointer is the static table.
    let api = unsafe { ffi::PyCapsule_Import(CAPSULE_NAME.as_ptr(), 0) } as *const CApi;
    let api = unsafe { api.as_ref() }.ok_or_else(|| PyErr::fetch(py))?;
    if !api.is_compatible() {
        return Err(PyTypeError::new_err(
            "the engine's C API is older than signified-api",
        ));
    }
    let kernel = Kernel {
        call: test_sum,
        ctx: Box::into_raw(Box::new(0u8)) as *mut c_void,
        release: Some(test_release),
    };
    // SAFETY: called with the GIL held, with live references.
    let obj =
        unsafe { (api.new_computed)(cls.as_ptr() as Object, kernel, args.as_ptr() as Object) };
    unsafe { Bound::from_owned_ptr_or_err(py, obj as *mut ffi::PyObject) }
}

/// `(kernel runs, contexts released)` of every `_native_test_sum` computed so far.
#[pyfunction]
pub fn _native_test_counts() -> (usize, usize) {
    (
        TEST_CALLS.load(Ordering::Relaxed),
        TEST_RELEASES.load(Ordering::Relaxed),
    )
}
