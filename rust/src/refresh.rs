//! Evaluating a Python computed (the host's half of a refresh; the engine
//! decides when one is needed), and the recursion guard around each nested
//! refresh.

use std::rc::Rc;

use pyo3::exceptions::{PyException, PyRecursionError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use signified_engine::refresh::{check_cycle, evaluate, must_refresh, settle};
use signified_engine::State;

use crate::hooks::{self, Hook};
use crate::native;
use crate::node::{CachedError, Compute, Node, NodeExt, RestorePoint};
use crate::values::{call_equal, has_changed, unref};

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
        if crate::stack::remaining().is_some_and(|free| free < MIN_FREE_STACK) {
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

/// Bring a computed up to date (see the engine's `ensure_uptodate`).
#[inline]
pub(crate) fn ensure_uptodate(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    signified_engine::refresh::ensure_uptodate(py, node, handle.as_unbound())
}

pub(crate) fn refresh(py: Python<'_>, node: &Rc<Node>, handle: &Bound<'_, PyAny>) -> PyResult<()> {
    let computed = node.computed_state();
    let data = &computed.data;
    let restore_point = data.restore.take();
    check_cycle(node)?;
    let forced = computed.state.get() == State::MustRefresh;
    let had_outcome = computed.state.get() != State::Uninitialized;
    let had_error = data.error.borrow().is_some();
    let compute = data
        .compute
        .borrow()
        .as_ref()
        .map(|compute| compute.clone_ref(py));
    let Some(compute) = compute else {
        return Err(PyRuntimeError::new_err(
            "Computed has no function: it was cleared by the garbage collector or never initialized",
        ));
    };

    // A native kernel sees the current value, so it can report an unchanged one.
    let current = match &compute {
        Compute::Native { .. } if had_outcome && !had_error => node
            .payload
            .value
            .borrow()
            .as_ref()
            .map(|value| value.clone_ref(py)),
        _ => None,
    };

    // 1) Evaluate with dependency tracking enabled, and 2) subscribe to what
    // this run read, even if it raised.
    let result = evaluate(node, || run_compute(py, &compute, current.as_ref()));
    drop(compute);

    let (mut next_value, mut next_error) = match result {
        Ok(value) => (Some(value), None),
        Err(error) if error.is_instance_of::<PyException>(py) => (None, Some(error)),
        Err(error) => return Err(escalate(node, error)),
    };

    // 3) A custom equality can declare a new value unchanged, which keeps the
    // previous object. Its reads are untracked and its errors are cached.
    let previous = node
        .payload
        .value
        .borrow()
        .as_ref()
        .map(|value| value.clone_ref(py));
    if had_outcome && !had_error {
        let equal = node
            .payload
            .equal
            .borrow()
            .as_ref()
            .map(|equal| equal.clone_ref(py));
        if let (Some(equal), Some(previous), Some(next)) = (&equal, &previous, &next_value) {
            if !previous.is(next) {
                match call_equal(equal.bind(py), previous.bind(py), next.bind(py)) {
                    Ok(true) => next_value = Some(previous.clone_ref(py)),
                    Ok(false) => {}
                    Err(error) if error.is_instance_of::<PyException>(py) => {
                        next_value = None;
                        next_error = Some(error);
                    }
                    Err(error) => return Err(escalate(node, error)),
                }
            }
        }
    }

    // 4) Cache the outcome. Every failed evaluation is a new outcome, and
    // recovery is a change even if the value equals the last successful one.
    let changed = if !had_outcome || had_error || next_error.is_some() {
        true
    } else {
        match (&previous, &next_value) {
            (Some(previous), Some(next)) => has_changed(previous.bind(py), next.bind(py))?,
            _ => true,
        }
    };
    let cached = next_error.map(|error| CachedError {
        traceback: error
            .traceback(py)
            .map(|traceback| traceback.into_any().unbind()),
        exception: error.into_value(py).into_any(),
    });
    let has_error = cached.is_some();
    let old_error = data.error.replace(cached);
    let mut old_value = None;
    if changed {
        old_value = node.payload.value.replace(next_value);
    }
    settle(node, changed || forced);
    drop((old_value, old_error, previous));
    if changed || forced {
        hooks::call(py, Hook::Updated, handle)?;
    }

    // 5) A binding read inside `at()` returns to its pre-context value and
    // version when it resolves to that value from the same, unchanged source.
    if let Some(point) = restore_point {
        if !forced && !has_error {
            restore(py, node, &point)?;
        }
    }
    Ok(())
}

/// A control-flow exception aborts evaluation instead of being cached; the
/// next read must retry even though dependencies were committed.
fn escalate(node: &Node, error: PyErr) -> PyErr {
    must_refresh(node);
    error
}

fn restore(py: Python<'_>, node: &Node, point: &RestorePoint) -> PyResult<()> {
    let same_source = point
        .holder
        .payload
        .value
        .borrow()
        .as_ref()
        .is_some_and(|current| current.is(&point.source));
    if !same_source || point.source_node.version.get() != point.source_version {
        return Ok(());
    }
    let current = node.raw_value(py);
    if has_changed(point.value.bind(py), &current)? {
        return Ok(());
    }
    let old = node.payload.value.replace(Some(point.value.clone_ref(py)));
    node.version.set(point.version);
    drop(old);
    Ok(())
}

fn run_compute(
    py: Python<'_>,
    compute: &Compute,
    current: Option<&Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    match compute {
        Compute::Native { kernel, args } => native::run(py, kernel, args, current),
        Compute::Function(f) => Ok(f.bind(py).call0()?.unbind()),
        Compute::Call { func, args } => {
            let func = func.bind(py);
            match args.as_slice() {
                [arg] => Ok(func.call1((unref(py, arg.bind(py))?,))?.unbind()),
                [left, right] => Ok(func
                    .call1((unref(py, left.bind(py))?, unref(py, right.bind(py))?))?
                    .unbind()),
                _ => {
                    let mut resolved = Vec::with_capacity(args.len());
                    for arg in args {
                        resolved.push(unref(py, arg.bind(py))?);
                    }
                    Ok(func.call1(PyTuple::new(py, resolved)?)?.unbind())
                }
            }
        }
        Compute::Source(holder) => {
            let source = unref(py, holder.bind(py))?;
            Ok(unref(py, &source)?.unbind())
        }
    }
}
