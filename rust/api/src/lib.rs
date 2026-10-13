//! The C API of [signified](https://github.com/dougmercer/signified)'s reactive engine, for Python
//! extension modules that compute reactive values natively.
//!
//! signified is a Python library of reactive values (`Signal`, `Computed`, `Effect`) whose engine,
//! `signified._core`, is a compiled extension. Through this API another extension creates a
//! `signified.Computed` whose value comes from a [`Kernel`], a C function it provides, instead of
//! a Python callable. The engine resolves and tracks the computed's reactive arguments and
//! refreshes it like any other `Computed` (lazily, only when an argument changed), but
//! evaluating it runs no Python code, so a graph of native computeds avoids the interpreter
//! between nodes. Python code reads and combines them like any other reactive value.
//!
//! This crate only describes the API: the [`CApi`] table that `signified._core` exports in a
//! capsule named [`CAPSULE_NAME`]. It does not link the engine (an extension could not share it
//! with `signified._core` anyway) and depends on no Python binding crate, so it works with pyo3,
//! raw `pyo3-ffi` or C. Signified releases after 0.7.0 export version 1 of the API.
//!
//! The API is internal and undocumented outside this crate, which is not published: an extension
//! that uses it copies this file. key3d vendors it as `rust/src/signified_api.rs`.
//!
//! # Getting the API
//!
//! Import the capsule once, with an attached thread state, and check that the engine provides
//! what this crate describes. With pyo3:
//!
//! ```ignore
//! use pyo3::ffi;
//! use signified_api::{CApi, CAPSULE_NAME};
//!
//! // SAFETY: attached; the capsule points to a static table that lives as long as the process.
//! let api = unsafe { ffi::PyCapsule_Import(CAPSULE_NAME.as_ptr(), 0) } as *const CApi;
//! if api.is_null() {
//!     return Err(PyErr::fetch(py)); // signified is missing, or older than this API
//! }
//! let api: &'static CApi = unsafe { &*api };
//! if !api.is_compatible() {
//!     return Err(PyRuntimeError::new_err("signified is older than this extension needs"));
//! }
//! ```
//!
//! # Making a native computed
//!
//! A [`Kernel`] is a function, a context pointer it receives, and a function that frees the
//! context. [`CApi::new_computed`] takes ownership of the context and returns the new computed:
//!
//! ```ignore
//! unsafe extern "C" fn sum(ctx: *mut c_void, args: *const Object, nargs: isize, previous: Object) -> Object {
//!     // Read the `nargs` borrowed arguments, return a new reference, or set an exception and
//!     // return null. Returning a new reference to `previous` reports an unchanged value.
//! }
//! unsafe extern "C" fn release(ctx: *mut c_void) {
//!     drop(Box::from_raw(ctx as *mut Context));
//! }
//!
//! let kernel = Kernel { call: sum, ctx: Box::into_raw(Box::new(context)).cast(), release: Some(release) };
//! let computed = unsafe { (api.new_computed)(computed_class, kernel, args_tuple) };
//! ```
//!
//! The repository's `rust/api-example` crate is a complete extension written this way, with
//! small safe wrappers over the raw functions, and tests run in CI.
//!
//! # Contract
//!
//! - **Thread state.** The engine calls every function here, and every function here must be
//!   called, with an attached thread state (holding the GIL on GIL builds of CPython). With pyo3,
//!   kernels and release functions get a `Python` token from `Python::assume_attached()`: the
//!   engine's caller is attached, but pyo3 in your extension does not know it.
//! - **Threads.** A signified graph is used from one thread at a time, but can move between
//!   threads. A kernel never runs concurrently for one computed, but may run on different
//!   threads over its life, so its context must be safe to send between threads.
//! - **References.** A kernel's arguments and `previous` are borrowed for the duration of the
//!   call. It returns a new reference, or null with a Python exception set.
//! - **Release.** `release` runs exactly once: when the computed is freed, or immediately if
//!   [`CApi::new_computed`] fails. It can run while the interpreter is finalizing, when only
//!   reference counting is safe (pyo3's `Python::attach` panics then, so do not use it there).
//! - **Garbage collection.** Python objects a context owns are invisible to the cyclic garbage
//!   collector. They must not refer back to the computed, or to anything that refers to it, or
//!   the cycle is never collected.
//! - **Panics.** Kernels and release functions must not unwind: a panic leaving an `extern "C"`
//!   function aborts the process. Catch panics (`std::panic::catch_unwind`) and set a Python
//!   exception instead.
//! - **Builds.** signified ships abi3 wheels for GIL builds of CPython 3.12 and later; the
//!   free-threaded build is not supported yet.
//!
//! # Versioning
//!
//! [`CApi::version`] is the API version the engine implements, and [`VERSION`] the one this crate
//! describes. A new API version only appends fields to [`CApi`] and never changes or removes
//! existing ones, so an extension built against version `n` works with every engine that
//! exports version `n` or later; [`CApi::is_compatible`] checks exactly that. Changing an existing
//! function would need a new capsule name.
//!
//! Copies of this file elsewhere (key3d's `rust/src/signified_api.rs`) rely on the layout that
//! the tests below pin. Keep changes append-only, bump [`VERSION`] when appending, and update the
//! copies.

#![cfg_attr(not(test), no_std)]
#![deny(missing_docs)]

use core::ffi::{c_void, CStr};

/// A `PyObject *`. The API does not depend on any Python binding crate.
pub type Object = *mut c_void;

/// Computes a native computed's value.
///
/// `ctx` is the [`Kernel::ctx`] the computed was made with. `args` points to `nargs` borrowed
/// references: the computed's arguments, with each `Signal`, `Computed` or `Binding` among them
/// replaced by its current value (reading it, so the computed depends on it). `previous` is the
/// computed's current value (borrowed), or null before its first value and after an evaluation
/// that raised.
///
/// Returns a new reference, or null with a Python exception set (which the computed caches and
/// raises to its readers, as it would an exception from a Python function). Returning `previous`
/// itself (a new reference to it) reports an unchanged value: the computed's version does not
/// change, so values computed from it are not recomputed.
///
/// # Safety
///
/// The engine calls it with an attached thread state, a `ctx` it was given, `nargs` valid
/// borrowed references at `args`, and `previous` valid or null. The function must not unwind
/// and must not keep the borrowed references past the call without taking new ones.
pub type KernelFn = unsafe extern "C" fn(
    ctx: *mut c_void,
    args: *const Object,
    nargs: isize,
    previous: Object,
) -> Object;

/// Frees a kernel's context. See the crate's [contract](crate#contract) for when it runs.
///
/// # Safety
///
/// The engine calls it once, with an attached thread state (possibly while the interpreter is
/// finalizing), and the kernel's `ctx`. The function must not unwind.
pub type ReleaseFn = unsafe extern "C" fn(ctx: *mut c_void);

/// A native function and the data it was made with.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Kernel {
    /// Computes the value.
    pub call: KernelFn,
    /// Passed to `call` and `release`; owned by the computed once [`CApi::new_computed`] is
    /// called, even if it fails.
    pub ctx: *mut c_void,
    /// Frees `ctx`, once, when the computed no longer needs it; `None` if nothing needs freeing.
    pub release: Option<ReleaseFn>,
}

/// The engine's C API: the table the [`CAPSULE_NAME`] capsule points to.
///
/// The table is static: a pointer to it stays valid for the life of the process.
#[repr(C)]
#[derive(Debug)]
pub struct CApi {
    /// The API version the engine implements (see [Versioning](crate#versioning)).
    pub version: u32,
    /// `size_of::<CApi>()` in the engine, which can be larger than in this crate.
    pub size: u32,
    /// A new instance of `cls` (`signified.Computed` or a subclass) computing `kernel` over the
    /// tuple `args`. Reactive items of `args` are resolved and tracked on every evaluation; other
    /// items are passed as they are. The first evaluation happens when the computed is read.
    ///
    /// Takes ownership of `kernel.ctx` even when it fails. Returns a new reference, or null with
    /// an exception set (a `TypeError` if `cls` is not a `Computed` class or `args` is not a
    /// tuple). Available from version 1.
    ///
    /// # Safety
    ///
    /// Call it with an attached thread state, with `cls` and `args` valid borrowed references,
    /// and a `kernel` whose functions follow [`KernelFn`] and [`ReleaseFn`].
    pub new_computed: unsafe extern "C" fn(cls: Object, kernel: Kernel, args: Object) -> Object,
}

impl CApi {
    /// Whether the engine provides everything this crate describes: an API version of at least
    /// [`VERSION`], and a table at least as large as this crate's [`CApi`].
    pub fn is_compatible(&self) -> bool {
        self.version >= VERSION && self.size as usize >= core::mem::size_of::<CApi>()
    }
}

/// The name of the capsule holding the [`CApi`]: `signified._core._C_API`.
pub const CAPSULE_NAME: &CStr = c"signified._core._C_API";

/// The API version this crate describes.
pub const VERSION: u32 = 1;

#[cfg(test)]
mod tests {
    use super::*;
    use core::mem::{offset_of, size_of};

    // Extensions built against earlier releases read these offsets: they must never change.
    #[test]
    fn the_version_1_layout_is_fixed() {
        let word = size_of::<usize>();
        assert_eq!(offset_of!(CApi, version), 0);
        assert_eq!(offset_of!(CApi, size), 4);
        assert_eq!(offset_of!(CApi, new_computed), 8);
        assert_eq!(size_of::<CApi>(), 8 + word);
        assert_eq!(offset_of!(Kernel, call), 0);
        assert_eq!(offset_of!(Kernel, ctx), word);
        assert_eq!(offset_of!(Kernel, release), 2 * word);
        assert_eq!(size_of::<Kernel>(), 3 * word);
        assert_eq!(size_of::<Option<ReleaseFn>>(), word);
    }

    #[test]
    fn compatibility_needs_the_version_and_the_size() {
        unsafe extern "C" fn new_computed(_: Object, _: Kernel, _: Object) -> Object {
            core::ptr::null_mut()
        }
        let api = |version, size| CApi {
            version,
            size,
            new_computed,
        };
        let size = size_of::<CApi>() as u32;
        assert!(api(VERSION, size).is_compatible());
        assert!(api(VERSION + 1, size + 8).is_compatible());
        assert!(!api(VERSION - 1, size).is_compatible());
        assert!(!api(VERSION, size - 8).is_compatible());
    }

    #[test]
    fn the_capsule_name_matches_the_module() {
        assert_eq!(CAPSULE_NAME.to_str(), Ok("signified._core._C_API"));
    }
}
