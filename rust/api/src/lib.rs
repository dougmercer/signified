//! The C API of `signified._core`, for extension modules that compute reactive values natively.
//!
//! An extension creates a `Computed` whose value comes from a [`Kernel`], a C function it
//! provides, instead of a Python callable. The engine tracks the computed's reactive arguments
//! and refreshes it like any other `Computed`, but evaluating it runs no Python code, so a graph
//! of native computeds avoids the interpreter between nodes.
//!
//! The engine exports a [`CApi`] table in a capsule named [`CAPSULE_NAME`]. This crate only
//! describes that table; it does not link the engine, which an extension could not share with
//! `signified._core` anyway (each extension module would get its own copy of the engine's state).
//! With pyo3:
//!
//! ```ignore
//! let api = unsafe { pyo3::ffi::PyCapsule_Import(signified_api::CAPSULE_NAME.as_ptr(), 0) }
//!     as *const signified_api::CApi;
//! // Check for null (the error is set), then `(*api).version >= signified_api::VERSION`.
//! ```
//!
//! Every function here is called with the GIL held (an attached thread state).

#![no_std]

use core::ffi::{c_void, CStr};

/// A `PyObject *`. The API does not depend on any Python binding crate.
pub type Object = *mut c_void;

/// Computes a native computed's value.
///
/// `args` points to `nargs` borrowed references: the computed's arguments, each Signal,
/// Computed or Binding among them replaced by its current value (reading it, so the computed
/// depends on it). `previous` is the computed's current value (borrowed), or null before its
/// first value and after an evaluation that raised.
///
/// Returns a new reference, or null with a Python exception set (which the computed caches and
/// raises to its readers, like an exception from a Python function). Returning `previous` itself
/// (a new reference to it) reports an unchanged value: the version does not change, so readers
/// that only depend on this computed stay current.
pub type KernelFn = unsafe extern "C" fn(
    ctx: *mut c_void,
    args: *const Object,
    nargs: isize,
    previous: Object,
) -> Object;

/// Frees a kernel's context.
pub type ReleaseFn = unsafe extern "C" fn(ctx: *mut c_void);

/// A native function and the data it was made with.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Kernel {
    pub call: KernelFn,
    /// Passed to `call` and `release`; owned by the computed once it is created.
    pub ctx: *mut c_void,
    /// Called once, with the GIL held, when the computed no longer needs `ctx` (or when creating
    /// it fails). Python objects `ctx` owns are invisible to the garbage collector, so they must
    /// not refer back to the computed.
    pub release: Option<ReleaseFn>,
}

/// The engine's C API (what the capsule points to).
#[repr(C)]
pub struct CApi {
    /// [`VERSION`] of the engine; later versions only add fields at the end.
    pub version: u32,
    /// `size_of::<CApi>()` in the engine.
    pub size: u32,
    /// A new instance of `cls` (`signified.Computed` or a subclass) computing `kernel` over the
    /// tuple `args`. Reactive items of `args` are read on every evaluation. Takes ownership of
    /// `kernel.ctx` even when it fails. Returns a new reference, or null with an exception set.
    pub new_computed: unsafe extern "C" fn(cls: Object, kernel: Kernel, args: Object) -> Object,
}

/// The name of the capsule holding the [`CApi`]: `signified._core._C_API`.
pub const CAPSULE_NAME: &CStr = c"signified._core._C_API";

/// The API version this crate describes.
pub const VERSION: u32 = 1;
