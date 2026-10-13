//! Pull: bring a computed up to date when it is read. A stale computed first
//! brings its computed dependencies up to date and compares versions, and
//! runs its function again only if one of them changed.

use std::rc::Rc;

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use crate::engine::node::{CachedError, Compute, ComputedState, Node, RestorePoint, Role, State};
use crate::engine::runtime::{bump_version, clock};
use crate::engine::tracking::{
    commit_refresh, end_frame, is_evaluating, push_frame, start_refresh,
};
use crate::hooks::{self, Hook};
use crate::native;
use crate::stack::RecursionGuard;
use crate::values::{call_equal, has_changed, unref};

/// Bring a computed up to date: nothing if it is fresh, a version check if it
/// is stale, and `refresh` if a dependency changed.
///
/// Always inlined, so it adds no stack frame to the recursion through it: a
/// read refreshes from the reader's frame, and `dependencies_changed` checks a
/// chain one frame per level. See `refresh` for why that matters.
#[inline(always)]
pub(crate) fn ensure_uptodate(
    py: Python<'_>,
    node: &Rc<Node>,
    handle: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let computed = node.computed_state();
    if computed.state.get() == State::Fresh {
        return Ok(());
    }
    let _guard = RecursionGuard::enter(py)?;
    // Any refresh attempt means observers must be told about the next change.
    computed.notified.set(false);
    let state = computed.state.get();
    // The graph has not changed since this node was last current.
    if state == State::Stale && computed.clock_seen.get() == clock() {
        computed.state.set(State::Fresh);
        return Ok(());
    }
    if state == State::Stale && !dependencies_changed(py, node)? {
        computed.state.set(State::Fresh);
        computed.clock_seen.set(clock());
        return Ok(());
    }
    refresh(py, node, handle)
}

/// Bring computed dependencies up to date, then report whether any
/// dependency's version differs from the one this consumer last saw.
pub(crate) fn dependencies_changed(py: Python<'_>, node: &Rc<Node>) -> PyResult<bool> {
    let deps = &node.reader_state().deps;
    let mut position = 0;
    loop {
        // Signals are compared in place; a computed may run Python code to
        // refresh, so it is copied out first.
        let computed = {
            let deps = deps.borrow();
            let Some(link) = deps.get(position) else {
                return Ok(false);
            };
            if !matches!(link.node.role, Role::Computed(_)) {
                if link.version != link.node.version.get() {
                    return Ok(true);
                }
                position += 1;
                continue;
            }
            (link.node.clone(), link.handle.clone_ref(py), link.version)
        };
        let (dep, handle, seen_version) = computed;
        ensure_uptodate(py, &dep, handle.bind(py))?;
        if seen_version != dep.version.get() {
            return Ok(true);
        }
        position += 1;
    }
}

/// Effects only: a dependency changed after this run read it.
pub(crate) fn invalidated_since_read(node: &Node) -> bool {
    node.reader_state().deps.borrow().iter().any(|link| {
        link.version != link.node.version.get()
            || matches!(&link.node.role, Role::Computed(computed) if computed.notified.get())
    })
}

/// Evaluate a stale computed whose dependencies changed.
///
/// A refresh that reads a stale computed refreshes it in a nested call, so a
/// deep graph recurses `read_computed` -> this -> `unref` -> `read_computed`:
/// three stack frames per level, with `ensure_uptodate` inlined into
/// `read_computed` and `run_compute` inlined here. Keep it at three: at four,
/// a graph ten levels deep overflowed the CPU's return-address predictor and
/// refreshed 9% slower on an M1. Never inlined, so callers of
/// `ensure_uptodate` stay small.
#[inline(never)]
fn refresh(py: Python<'_>, node: &Rc<Node>, handle: &Bound<'_, PyAny>) -> PyResult<()> {
    let computed = node.computed_state();
    let restore_point = computed.restore.take();
    if computed.computing.get() {
        // On this thread it is a cycle; otherwise another thread is running it.
        return Err(PyRuntimeError::new_err(if is_evaluating(node) {
            "Cycle detected while evaluating Computed"
        } else {
            "Computed is being evaluated on another thread"
        }));
    }
    let forced = computed.state.get() == State::MustRefresh;
    let had_outcome = computed.state.get() != State::Uninitialized;
    let had_error = computed.error.borrow().is_some();
    let compute = computed.compute.borrow().clone();
    let Some(compute) = compute else {
        return Err(PyRuntimeError::new_err(
            "Computed has no function: it was cleared by the garbage collector or never initialized",
        ));
    };

    // A native kernel sees the current value, so it can report an unchanged one.
    let current = match &*compute {
        Compute::Native { .. } if had_outcome && !had_error => node
            .value
            .borrow()
            .as_ref()
            .map(|value| value.clone_ref(py)),
        _ => None,
    };

    // 1) Evaluate with dependency tracking enabled.
    computed.computing.set(true);
    start_refresh(node);
    let depth = push_frame(Some(node.clone()));
    let mut result = run_compute(py, &compute, current.as_ref());
    if let Err(error) = end_frame(depth) {
        result = Err(error);
    }
    computed.computing.set(false);
    // 2) Subscribe to what this run read, even if it raised.
    commit_refresh(node);
    drop(compute);

    let (mut next_value, mut next_error) = match result {
        Ok(value) => (Some(value), None),
        Err(error) if error.is_instance_of::<PyException>(py) => (None, Some(error)),
        Err(error) => return Err(escalate(computed, error)),
    };

    // 3) A custom equality can declare a new value unchanged, which keeps the
    // previous object. Its reads are untracked and its errors are cached.
    let previous = node
        .value
        .borrow()
        .as_ref()
        .map(|value| value.clone_ref(py));
    if had_outcome && !had_error {
        let equal = node
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
                    Err(error) => return Err(escalate(computed, error)),
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
    let old_error = computed.error.replace(cached);
    computed.state.set(State::Fresh);
    let mut old_value = None;
    if changed {
        old_value = node.value.replace(next_value);
        computed.clock_seen.set(bump_version(node));
    } else if forced {
        computed.clock_seen.set(bump_version(node));
    } else {
        computed.clock_seen.set(clock());
    }
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
fn escalate(computed: &ComputedState, error: PyErr) -> PyErr {
    if computed.state.get() < State::MustRefresh {
        computed.state.set(State::MustRefresh);
    }
    error
}

fn restore(py: Python<'_>, node: &Node, point: &RestorePoint) -> PyResult<()> {
    let same_source = point
        .holder
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
    let old = node.value.replace(Some(point.value.clone_ref(py)));
    node.version.set(point.version);
    drop(old);
    Ok(())
}

/// Inlined into `refresh` to keep nested refreshes shallow; see there.
#[inline(always)]
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
