//! An example extension whose `signified.Computed` values are evaluated by Rust kernels, through
//! `signified-api`.
//!
//! The first half is a small safe layer over the raw API that an extension can copy: [`api`]
//! imports the capsule once, [`NativeKernel`] is the trait a kernel implements, and
//! [`new_computed`] makes a computed from one. The second half is the kernel this module exports.

use std::ffi::c_void;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr::null_mut;
use std::sync::atomic::{AtomicUsize, Ordering};

use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::panic::PanicException;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyFloat, PyTuple};
use pyo3::{ffi, Borrowed};
use signified_api::{CApi, Kernel, Object, CAPSULE_NAME};

// The safe layer.

static API: PyOnceLock<&'static CApi> = PyOnceLock::new();

/// signified's C API, imported once.
fn api(py: Python<'_>) -> PyResult<&'static CApi> {
    API.get_or_try_init(py, || {
        // SAFETY: attached; the capsule points to a static table that lives as long as the process.
        let api = unsafe { ffi::PyCapsule_Import(CAPSULE_NAME.as_ptr(), 0) } as *const CApi;
        let api = unsafe { api.as_ref() }.ok_or_else(|| PyErr::fetch(py))?;
        if !api.is_compatible() {
            return Err(PyRuntimeError::new_err(
                "the installed signified is older than this extension needs",
            ));
        }
        Ok(api)
    })
    .copied()
}

/// What a native computed computes. `Send`: a signified graph can move between threads.
trait NativeKernel: Send + Sized + 'static {
    /// The value from the computed's arguments (reactive ones already resolved), given its
    /// current value, if it has one. Returning `previous` reports an unchanged value.
    fn compute<'py>(
        &self,
        py: Python<'py>,
        args: &[Borrowed<'_, 'py, PyAny>],
        previous: Option<Borrowed<'_, 'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>>;

    /// Drop the kernel. This can run while the interpreter finalizes; release Python objects
    /// the kernel owns through `py` (`Py::into_bound`), since pyo3 does not know the caller is
    /// attached and would defer their decrefs.
    fn release(self, _py: Python<'_>) {}
}

unsafe extern "C" fn call<K: NativeKernel>(
    ctx: *mut c_void,
    args: *const Object,
    nargs: isize,
    previous: Object,
) -> Object {
    // SAFETY: signified calls kernels attached, with `nargs` borrowed arguments and a borrowed
    // (or null) current value; `ctx` is the `K` that `new_computed` boxed.
    let py = unsafe { Python::assume_attached() };
    let kernel = unsafe { &*(ctx as *const K) };
    let args: Vec<_> = (0..nargs as usize)
        .map(|index| unsafe { Borrowed::from_ptr(py, *args.add(index) as *mut ffi::PyObject) })
        .collect();
    let previous = (!previous.is_null())
        .then(|| unsafe { Borrowed::from_ptr(py, previous as *mut ffi::PyObject) });
    // A panic must not unwind into signified.
    let result = catch_unwind(AssertUnwindSafe(|| kernel.compute(py, &args, previous)))
        .unwrap_or_else(|_| Err(PanicException::new_err("a native kernel panicked")));
    match result {
        Ok(value) => value.into_ptr() as Object,
        Err(error) => {
            error.restore(py);
            null_mut()
        }
    }
}

unsafe extern "C" fn release<K: NativeKernel>(ctx: *mut c_void) {
    // SAFETY: called once, attached (possibly while the interpreter finalizes, when
    // `Python::attach` would panic), with the context `new_computed` boxed.
    let py = unsafe { Python::assume_attached() };
    let kernel = unsafe { Box::from_raw(ctx as *mut K) };
    let _ = catch_unwind(AssertUnwindSafe(|| kernel.release(py)));
}

/// A new `signified.Computed` evaluated by *kernel* over *args*.
fn new_computed<'py, K: NativeKernel>(
    py: Python<'py>,
    kernel: K,
    args: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyAny>> {
    let api = api(py)?;
    let computed_class = py.import("signified")?.getattr("Computed")?;
    let kernel = Kernel {
        call: call::<K>,
        ctx: Box::into_raw(Box::new(kernel)) as *mut c_void,
        release: Some(release::<K>),
    };
    // SAFETY: attached, with live references; signified owns the context from here.
    let computed = unsafe {
        (api.new_computed)(
            computed_class.as_ptr() as Object,
            kernel,
            args.as_ptr() as Object,
        )
    };
    unsafe { Bound::from_owned_ptr_or_err(py, computed as *mut ffi::PyObject) }
}

// The module.

static RELEASED: AtomicUsize = AtomicUsize::new(0);

/// `sum(weight * value)` over the computed's arguments.
struct WeightedSum {
    weights: Vec<f64>,
}

impl NativeKernel for WeightedSum {
    fn compute<'py>(
        &self,
        py: Python<'py>,
        args: &[Borrowed<'_, 'py, PyAny>],
        previous: Option<Borrowed<'_, 'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut total = 0.0;
        for (weight, value) in self.weights.iter().zip(args) {
            let Ok(value) = value.extract::<f64>() else {
                return Err(PyTypeError::new_err(format!(
                    "expected a number, got {}",
                    value.repr()?
                )));
            };
            total += weight * value;
        }
        // An equal sum keeps the previous object: the computed's readers are not recomputed.
        if let Some(previous) = previous {
            if previous.extract::<f64>().is_ok_and(|value| value == total) {
                return Ok(previous.to_owned());
            }
        }
        Ok(PyFloat::new(py, total).into_any())
    }

    fn release(self, _py: Python<'_>) {
        RELEASED.fetch_add(1, Ordering::Relaxed);
    }
}

/// A `signified.Computed` of `sum(weight * value)`, evaluated natively. Each value can be a
/// number or a reactive value holding one (a `Signal`, `Computed` or `Binding`).
#[pyfunction]
#[pyo3(signature = (weights, *values))]
fn weighted_sum<'py>(
    py: Python<'py>,
    weights: Vec<f64>,
    values: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyAny>> {
    if weights.len() != values.len() {
        return Err(PyTypeError::new_err(
            "weighted_sum needs one weight per value",
        ));
    }
    new_computed(py, WeightedSum { weights }, values)
}

/// How many kernels have been released (for tests).
#[pyfunction]
fn released() -> usize {
    RELEASED.load(Ordering::Relaxed)
}

#[pymodule]
fn signified_api_example(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(weighted_sum, module)?)?;
    module.add_function(wrap_pyfunction!(released, module)?)?;
    Ok(())
}
