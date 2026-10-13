//! Guarding nested refreshes: how much native stack the current thread has
//! left, and the recursion guard each nested refresh holds.
//!
//! `stacker` reads a thread's stack bounds from `pthread_getattr_np`. For the
//! main thread, musl reports only the part of the stack mapped so far (about
//! 128 KiB at startup) rather than the size it can grow to, which would make
//! every refresh look too deep. Under musl, the main thread's bound is worked
//! out from `RLIMIT_STACK` instead.

use pyo3::exceptions::PyRecursionError;
use pyo3::prelude::*;

/// Free native stack below the current frame, if known.
pub(crate) fn remaining() -> Option<usize> {
    #[cfg(all(target_os = "linux", target_env = "musl"))]
    match musl::stack_end() {
        musl::StackEnd::Reported => {}
        musl::StackEnd::At(end) => {
            let here = 0u8;
            return Some((std::ptr::addr_of!(here) as usize).saturating_sub(end));
        }
        musl::StackEnd::Unknown => return None,
    }
    stacker::remaining_stack()
}

/// Native stack to keep free for the Python code a refresh may call.
const MIN_FREE_STACK: usize = 256 * 1024;

/// Refreshes allowed to nest under Emscripten (Pyodide). There, native frames
/// also use the JavaScript engine's stack, about 1 MB in Node and Chrome,
/// which neither check in `RecursionGuard` sees, and overflowing it aborts the
/// interpreter. A chain of computeds that each call a Python function
/// overflowed it at about 520 levels in Node 25; this leaves room for smaller
/// worker stacks.
#[cfg(target_os = "emscripten")]
const MAX_NESTED_REFRESHES: u32 = 250;

#[cfg(target_os = "emscripten")]
static NESTED_REFRESHES: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);

fn too_deep() -> PyErr {
    PyRecursionError::new_err("maximum recursion depth exceeded while refreshing a reactive value")
}

/// Holds one level of Python's recursion budget, so a very deep graph raises
/// `RecursionError` instead of overflowing the native stack. Python 3.12 and
/// 3.13 count calls rather than measuring the stack, and worker threads have
/// small stacks, so the remaining stack is checked directly as well.
pub(crate) struct RecursionGuard;

impl RecursionGuard {
    pub(crate) fn enter(py: Python<'_>) -> PyResult<RecursionGuard> {
        if remaining().is_some_and(|free| free < MIN_FREE_STACK) {
            return Err(too_deep());
        }
        #[cfg(target_os = "emscripten")]
        if NESTED_REFRESHES.load(std::sync::atomic::Ordering::Relaxed) >= MAX_NESTED_REFRESHES {
            return Err(too_deep());
        }
        let failed = unsafe {
            pyo3::ffi::Py_EnterRecursiveCall(c" while refreshing a reactive value".as_ptr())
        };
        if failed != 0 {
            return Err(PyErr::fetch(py));
        }
        #[cfg(target_os = "emscripten")]
        NESTED_REFRESHES.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(RecursionGuard)
    }
}

impl Drop for RecursionGuard {
    fn drop(&mut self) {
        #[cfg(target_os = "emscripten")]
        NESTED_REFRESHES.fetch_sub(1, std::sync::atomic::Ordering::Relaxed);
        unsafe { pyo3::ffi::Py_LeaveRecursiveCall() };
    }
}

#[cfg(all(target_os = "linux", target_env = "musl"))]
mod musl {
    use std::mem::MaybeUninit;

    /// Where the current thread's stack ends.
    #[derive(Clone, Copy)]
    pub(super) enum StackEnd {
        /// Not the main thread; musl reports its bounds correctly.
        Reported,
        /// The lowest address the main thread's stack can grow to.
        At(usize),
        /// The main thread, with an unlimited or unreadable stack size.
        Unknown,
    }

    thread_local! {
        static STACK_END: StackEnd = unsafe { find_stack_end() };
    }

    pub(super) fn stack_end() -> StackEnd {
        STACK_END.with(|end| *end)
    }

    unsafe fn find_stack_end() -> StackEnd {
        if libc::gettid() != libc::getpid() {
            return StackEnd::Reported;
        }
        // For the main thread, musl reports the top of the stack and the size
        // mapped so far; the stack can grow down from that top to the limit.
        let mut attr = MaybeUninit::<libc::pthread_attr_t>::uninit();
        if libc::pthread_attr_init(attr.as_mut_ptr()) != 0 {
            return StackEnd::Unknown;
        }
        let mut attr = attr.assume_init();
        let mut low = std::ptr::null_mut();
        let mut mapped = 0;
        let found = libc::pthread_getattr_np(libc::pthread_self(), &mut attr) == 0
            && libc::pthread_attr_getstack(&attr, &mut low, &mut mapped) == 0;
        libc::pthread_attr_destroy(&mut attr);
        let mut limit = MaybeUninit::<libc::rlimit>::uninit();
        if !found || libc::getrlimit(libc::RLIMIT_STACK, limit.as_mut_ptr()) != 0 {
            return StackEnd::Unknown;
        }
        let size = limit.assume_init().rlim_cur;
        if size == libc::RLIM_INFINITY {
            return StackEnd::Unknown;
        }
        let top = low as usize + mapped;
        StackEnd::At(top.saturating_sub(size as usize))
    }
}
