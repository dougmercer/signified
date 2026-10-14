//! Sampled evaluations: a value as if a signal held another value.
//!
//! `sample(value, signal, at)` is a computed whose function is
//! `Compute::Sample`. When `at` differs from the signal's value, its refresh
//! evaluates `value` under a substitution. While one is active on any thread,
//! reads come here (see `hooks::special_read`):
//! - a read of the substituted signal returns `at`;
//! - a computed that depends on it, directly or not, is computed again into
//!   the substitution's own results, never into its node;
//! - anything else is read from the live graph as usual.
//!
//! Each read of the live graph meanwhile is tracked as a dependency of the
//! sample, but the substituted signal is not, so changing only that signal
//! leaves the sample's cached value alone. Nothing the live graph caches
//! changes.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::intern;
use pyo3::prelude::*;

use crate::engine::node::{Node, Role, State};
use crate::engine::refresh::run_compute;
use crate::engine::runtime::with_rt;
use crate::engine::tracking::{end_frame, push_frame, track_read_by};
use crate::hooks;
use crate::stack::RecursionGuard;
use crate::values::{call_equal, has_changed, unref};

type Stack = RefCell<Vec<Option<Rc<Substitution>>>>;

/// This thread's active substitutions, innermost last. `None` marks a live
/// refresh, which reads the live graph whatever is active below it. Part of
/// the runtime.
pub(crate) struct Substitutions(Stack);

impl Substitutions {
    pub(crate) const fn new() -> Substitutions {
        Substitutions(RefCell::new(Vec::new()))
    }
}

fn with_stack<R>(f: impl FnOnce(&Stack) -> R) -> R {
    with_rt(|rt| f(&rt.substitutions.0))
}

/// One evaluation of a value as if `signal` held `value`.
struct Substitution {
    signal: Rc<Node>,
    value: Py<PyAny>,
    /// The live sample whose refresh began the outermost substitution; each
    /// read of the live graph is a dependency of it.
    reader: Rc<Node>,
    /// Computeds evaluated under this substitution, by node address.
    results: RefCell<HashMap<usize, Entry>>,
    /// Whether a fresh live computed depends on a substituted signal.
    depends: RefCell<HashMap<usize, bool>>,
}

struct Entry {
    /// Keeps the address used as the key from being reused.
    _node: Rc<Node>,
    outcome: Outcome,
}

enum Outcome {
    Computing,
    Value(Py<PyAny>),
    Error {
        exception: Py<PyAny>,
        traceback: Option<Py<PyAny>>,
    },
}

fn key(node: &Rc<Node>) -> usize {
    Rc::as_ptr(node) as usize
}

/// Keeps a substitution, or a live refresh's marker, on this thread's stack
/// while it lives.
pub(crate) struct Pushed {
    substitution: bool,
}

impl Pushed {
    fn push(entry: Option<Rc<Substitution>>) -> Pushed {
        let substitution = entry.is_some();
        with_stack(|stack| stack.borrow_mut().push(entry));
        if substitution {
            hooks::begin_sampling();
        }
        Pushed { substitution }
    }
}

impl Drop for Pushed {
    fn drop(&mut self) {
        let popped = with_stack(|stack| stack.borrow_mut().pop());
        if self.substitution {
            hooks::end_sampling();
        }
        // Dropping a substitution drops Python objects; nothing is borrowed.
        drop(popped);
    }
}

/// Hide this thread's substitutions during a live refresh, so the live graph
/// is never computed under one. Free unless a sample is being evaluated.
#[inline]
pub(crate) fn live_refresh() -> Option<Pushed> {
    if !hooks::sampling_active() || with_stack(|stack| stack.borrow().is_empty()) {
        return None;
    }
    Some(Pushed::push(None))
}

/// The innermost substitution, unless a live refresh hides it.
fn innermost() -> Option<Rc<Substitution>> {
    with_stack(|stack| stack.borrow().last().cloned().flatten())
}

/// The value an active substitution gives `signal`, innermost first.
fn substituted_value(py: Python<'_>, signal: &Rc<Node>) -> Option<Py<PyAny>> {
    with_stack(|stack| {
        for entry in stack.borrow().iter().rev() {
            let entry = entry.as_ref()?;
            if Rc::ptr_eq(&entry.signal, signal) {
                return Some(entry.value.clone_ref(py));
            }
        }
        None
    })
}

/// The signals that active substitutions replace.
fn substituted_signals() -> Vec<Rc<Node>> {
    with_stack(|stack| {
        stack
            .borrow()
            .iter()
            .rev()
            .map_while(|entry| entry.as_ref().map(|entry| entry.signal.clone()))
            .collect()
    })
}

/// Answer a read while a sample may be under evaluation: `Some` for the
/// substituted signal or a computed evaluated under the substitution, `None`
/// to read the live graph as usual.
pub(crate) fn read<'py>(py: Python<'py>, node: &Rc<Node>) -> PyResult<Option<Bound<'py, PyAny>>> {
    let Some(substitution) = innermost() else {
        return Ok(None);
    };
    match &node.role {
        Role::Signal => Ok(substituted_value(py, node).map(|value| value.into_bound(py))),
        Role::Computed(computed) => {
            let evaluated = substitution.results.borrow().contains_key(&key(node));
            if !evaluated
                && computed.state.get() == State::Fresh
                && !depends_on_substitution(py, &substitution, node)
            {
                return Ok(None);
            }
            evaluate_under(py, &substitution, node).map(Some)
        }
        Role::Effect(_) => Ok(None),
    }
}

/// Whether a fresh live computed's value could differ under the active
/// substitutions: some dependency, directly or not, is a substituted signal
/// or a computed that is not fresh. A fresh computed's dependencies are its
/// current ones, and a computed takes the same branches when its inputs are
/// the same, so otherwise its live value is the substituted one.
///
/// Every other signal found becomes a dependency of the sample. A change to
/// one can make the computed read a substituted signal while its own value
/// stays the same, so the sample must look again.
fn depends_on_substitution(py: Python<'_>, substitution: &Substitution, start: &Rc<Node>) -> bool {
    if let Some(&known) = substitution.depends.borrow().get(&key(start)) {
        return known;
    }
    let signals = substituted_signals();
    // Depth-first, with an explicit stack so long chains cannot overflow.
    let mut path: Vec<(Rc<Node>, usize)> = vec![(start.clone(), 0)];
    let found = loop {
        let Some((node, index)) = path.last_mut() else {
            break false;
        };
        let next = node
            .reader_state()
            .deps
            .borrow()
            .get(*index)
            .map(|link| (link.node.clone(), link.handle.clone_ref(py)));
        *index += 1;
        let Some((dep, handle)) = next else {
            if let Some((node, _)) = path.pop() {
                substitution.depends.borrow_mut().insert(key(&node), false);
            }
            continue;
        };
        match &dep.role {
            Role::Signal => {
                if signals.iter().any(|signal| Rc::ptr_eq(signal, &dep)) {
                    break true;
                }
                track_read_by(&substitution.reader, &dep, handle.bind(py));
            }
            Role::Computed(computed) => {
                let known = substitution.depends.borrow().get(&key(&dep)).copied();
                match known {
                    Some(true) => break true,
                    Some(false) => {}
                    None if computed.state.get() != State::Fresh => break true,
                    None => path.push((dep, 0)),
                }
            }
            Role::Effect(_) => {}
        }
    };
    if found {
        let mut depends = substitution.depends.borrow_mut();
        for (node, _) in &path {
            depends.insert(key(node), true);
        }
    }
    found
}

/// Compute `node` under `substitution`, once per substitution; a later read
/// returns the same value or raises the same exception.
fn evaluate_under<'py>(
    py: Python<'py>,
    substitution: &Rc<Substitution>,
    node: &Rc<Node>,
) -> PyResult<Bound<'py, PyAny>> {
    let key = key(node);
    let earlier = substitution
        .results
        .borrow()
        .get(&key)
        .map(|entry| match &entry.outcome {
            Outcome::Computing => None,
            Outcome::Value(value) => Some(Ok(value.clone_ref(py))),
            Outcome::Error {
                exception,
                traceback,
            } => Some(Err((
                exception.clone_ref(py),
                traceback.as_ref().map(|traceback| traceback.clone_ref(py)),
            ))),
        });
    match earlier {
        Some(None) => {
            return Err(PyRuntimeError::new_err(
                "Cycle detected while evaluating Computed",
            ))
        }
        Some(Some(Ok(value))) => return Ok(value.into_bound(py)),
        Some(Some(Err((exception, traceback)))) => {
            let exception = exception.into_bound(py);
            // Reset the traceback so repeated reads do not accumulate frames.
            exception.setattr(intern!(py, "__traceback__"), traceback)?;
            return Err(PyErr::from_value(exception));
        }
        None => {}
    }

    let _guard = RecursionGuard::enter(py)?;
    let compute = node.computed_state().compute.borrow().clone();
    let Some(compute) = compute else {
        return Err(PyRuntimeError::new_err(
            "Computed has no function: it was cleared by the garbage collector or never initialized",
        ));
    };
    substitution.results.borrow_mut().insert(
        key,
        Entry {
            _node: node.clone(),
            outcome: Outcome::Computing,
        },
    );
    add_sampler(node, &substitution.reader);
    // Reads are tracked for the sample, even inside an `untracked()` block
    // that led here: in the live graph this computed would track them itself.
    let depth = push_frame(Some(substitution.reader.clone()));
    let mut result = run_compute(py, &compute, None, &substitution.reader);
    if let Err(error) = end_frame(depth) {
        result = Err(error);
    }
    drop(compute);

    let outcome = match &result {
        Ok(value) => Some(Outcome::Value(value.clone_ref(py))),
        Err(error) if error.is_instance_of::<PyException>(py) => Some(Outcome::Error {
            exception: error.value(py).clone().into_any().unbind(),
            traceback: error
                .traceback(py)
                .map(|traceback| traceback.into_any().unbind()),
        }),
        // A control-flow exception is not a result.
        Err(_) => None,
    };
    let replaced = match outcome {
        Some(outcome) => substitution.results.borrow_mut().insert(
            key,
            Entry {
                _node: node.clone(),
                outcome,
            },
        ),
        None => substitution.results.borrow_mut().remove(&key),
    };
    drop(replaced);
    result.map(|value| value.into_bound(py))
}

/// Record that `sample` computed `node` for itself. The sample does not
/// observe `node`, since a change to the signal it replaces must not reach
/// it, but an explicit invalidation of `node` must (see `invalidation`). An
/// entry stays after a later evaluation stops computing `node`, which costs
/// at most one extra evaluation.
fn add_sampler(node: &Node, sample: &Rc<Node>) {
    let mut samplers = node.computed_state().samplers.borrow_mut();
    samplers.retain(|sampler| sampler.strong_count() > 0);
    if !samplers
        .iter()
        .any(|sampler| sampler.as_ptr() == Rc::as_ptr(sample))
    {
        samplers.push(Rc::downgrade(sample));
    }
}

/// `Compute::Sample`: `value` as if `signal` held `at`'s value. `at` is read
/// first, as the caller sees it. `reader` is the live sample being refreshed,
/// or the one whose refresh began the outermost substitution.
pub(crate) fn evaluate(
    py: Python<'_>,
    reader: &Rc<Node>,
    value: &Py<PyAny>,
    signal: &Rc<Node>,
    signal_handle: &Py<PyAny>,
    at: &Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let at = unref(py, at.bind(py))?;
    let substituted = substituted_value(py, signal);
    let current = match &substituted {
        Some(value) => value.bind(py).clone(),
        None => signal.raw_value(py),
    };
    // At the signal's own value, `value` is read as it is, as `Signal.at()`
    // would be a no-op. The signal is then a dependency too: once it moves
    // off `at`, the result must be found again, even if `value`'s own value
    // happens not to change.
    if !differs(py, signal, &current, &at)? {
        if substituted.is_none() {
            track_read_by(reader, signal, signal_handle.bind(py));
        }
        return Ok(unref(py, value.bind(py))?.unbind());
    }
    let substitution = Rc::new(Substitution {
        signal: signal.clone(),
        value: at.unbind(),
        reader: reader.clone(),
        results: RefCell::default(),
        depends: RefCell::default(),
    });
    let pushed = Pushed::push(Some(substitution));
    let result = unref(py, value.bind(py)).map(Bound::unbind);
    drop(pushed);
    result
}

/// Whether assigning `at` to `signal` would change it, by the rule
/// assignment uses.
fn differs(
    py: Python<'_>,
    signal: &Node,
    current: &Bound<'_, PyAny>,
    at: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    if !has_changed(current, at)? {
        return Ok(false);
    }
    let equal = signal
        .equal
        .borrow()
        .as_ref()
        .map(|equal| equal.clone_ref(py));
    match equal {
        Some(equal) => Ok(!call_equal(equal.bind(py), current, at)?),
        None => Ok(true),
    }
}
