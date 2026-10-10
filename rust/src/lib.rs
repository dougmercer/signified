//! `signified._core`: the reactive graph engine (spike).
//!
//! A port of the propagation algorithm in `signified/_reactive.py`: push
//! invalidation, pull refresh with version checks, mark-and-sweep dependency
//! tracking. Python sees `Signal` and `Computed` base classes; the public
//! classes in `signified/_spike.py` subclass them together with the mixin.
//!
//! Rules that keep this sound while Python code runs inside the engine:
//! - Never call Python, and never drop a `Py`, while a `RefCell` in a `Node` is
//!   borrowed. Copy what you need out, release the borrow, then call or drop.
//! - `__traverse__` only uses `try_borrow`; a busy cell is skipped.
//! - State is only touched while attached to an interpreter that holds the GIL,
//!   which serializes all access; see the `Send`/`Sync` impls below. The module
//!   declares `gil_used = true`, so a free-threaded interpreter re-enables the
//!   GIL when it is imported.

use std::cell::{Cell, RefCell};
use std::collections::HashSet;
use std::sync::{Arc, OnceLock, Weak};

use pyo3::exceptions::{PyException, PyRecursionError, PyRuntimeError};
use pyo3::gc::PyVisit;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyBytes, PyComplex, PyFloat, PyInt, PyString, PyTuple, PyType, PyWeakrefReference,
};
use pyo3::PyTraverseError;

// ---------------------------------------------------------------------------
// Graph state
// ---------------------------------------------------------------------------

/// Staleness of a computed node; ordered by invalidation priority, as in `_State`.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
enum State {
    Fresh,
    Stale,
    MustRefresh,
    Uninitialized,
}

const NEVER: u64 = u64::MAX;

/// A subscriber of a node. Engine nodes are held weakly in Rust; Python
/// observers added with `subscribe()` are held through Python weakrefs.
enum Observer {
    Node(Weak<Node>),
    Python(Py<PyWeakrefReference>),
}

impl Observer {
    fn clone_ref(&self, py: Python<'_>) -> Observer {
        match self {
            Observer::Node(weak) => Observer::Node(weak.clone()),
            Observer::Python(reference) => Observer::Python(reference.clone_ref(py)),
        }
    }

    fn is_alive(&self, py: Python<'_>) -> bool {
        match self {
            Observer::Node(weak) => weak.strong_count() > 0,
            Observer::Python(reference) => reference.bind(py).upgrade().is_some(),
        }
    }
}

/// How a computed node produces its value.
enum Compute {
    /// A zero-argument Python callable (`Computed(fn)`).
    Function(Py<PyAny>),
    /// `func(*resolved args)`, with reactive arguments resolved in Rust.
    Operator {
        func: Py<PyAny>,
        args: Vec<Py<PyAny>>,
    },
}

impl Compute {
    fn clone_ref(&self, py: Python<'_>) -> Compute {
        match self {
            Compute::Function(f) => Compute::Function(f.clone_ref(py)),
            Compute::Operator { func, args } => Compute::Operator {
                func: func.clone_ref(py),
                args: args.iter().map(|arg| arg.clone_ref(py)).collect(),
            },
        }
    }
}

/// Edge from a computed node to one dependency, reused across refreshes.
struct DepLink {
    node: Arc<Node>,
    /// The dependency's Python object; keeps it alive and is visible to the GC.
    handle: Py<PyAny>,
    version: u64,
    read_version: u64,
    seen: u64,
    active: bool,
}

/// A failed evaluation, kept as Python objects so the GC can traverse it.
struct CachedError {
    exception: Py<PyAny>,
    traceback: Option<Py<PyAny>>,
}

struct Node {
    is_computed: bool,
    value: RefCell<Option<Py<PyAny>>>,
    version: Cell<u64>,
    observers: RefCell<Vec<Observer>>,
    compute: RefCell<Option<Compute>>,
    state: Cell<State>,
    computing: Cell<bool>,
    notified: Cell<bool>,
    clock_seen: Cell<u64>,
    token: Cell<u64>,
    deps: RefCell<Vec<DepLink>>,
    error: RefCell<Option<CachedError>>,
}

// SAFETY: every field is read and written only by code running while attached
// to the interpreter, and the GIL lets one thread run at a time (the module is
// `gil_used = true`). No borrow is held across a call into Python, so a thread
// switch inside such a call never observes a cell mid-update. Concurrent use
// from several threads is no more supported than with the Python engine, but
// it cannot cause a data race.
unsafe impl Send for Node {}
unsafe impl Sync for Node {}

impl Node {
    fn new(is_computed: bool, value: Option<Py<PyAny>>, compute: Option<Compute>) -> Node {
        Node {
            is_computed,
            value: RefCell::new(value),
            version: Cell::new(0),
            observers: RefCell::new(Vec::new()),
            compute: RefCell::new(compute),
            state: Cell::new(if is_computed {
                State::Uninitialized
            } else {
                State::Fresh
            }),
            computing: Cell::new(false),
            notified: Cell::new(false),
            clock_seen: Cell::new(NEVER),
            token: Cell::new(0),
            deps: RefCell::new(Vec::new()),
            error: RefCell::new(None),
        }
    }
}

// ---------------------------------------------------------------------------
// Runtime: version clock, tracking frames, notification wave
// ---------------------------------------------------------------------------

struct Runtime {
    clock: Cell<u64>,
    /// The node being evaluated, innermost last; `None` marks an untracked block.
    frames: RefCell<Vec<Option<Arc<Node>>>>,
    /// Nodes already notified in the current wave, as in `_scheduler._notified`.
    wave: RefCell<HashSet<usize>>,
    wave_depth: Cell<u32>,
    /// Type objects whose `.value` is the engine's own getter (see `resolve_arg`).
    standard_types: RefCell<Vec<usize>>,
}

// SAFETY: as for `Node`; one runtime is shared by all threads, like the
// module-level state of the Python engine, and the GIL serializes access.
unsafe impl Send for Runtime {}
unsafe impl Sync for Runtime {}

fn rt() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(|| Runtime {
        clock: Cell::new(0),
        frames: RefCell::new(Vec::new()),
        wave: RefCell::new(HashSet::new()),
        wave_depth: Cell::new(0),
        standard_types: RefCell::new(Vec::new()),
    })
}

fn clock() -> u64 {
    rt().clock.get()
}

fn bump_version(node: &Node) -> u64 {
    let rt = rt();
    let version = rt.clock.get() + 1;
    rt.clock.set(version);
    node.version.set(version);
    version
}

fn current_reader() -> Option<Arc<Node>> {
    rt().frames.borrow().last().cloned().flatten()
}

fn is_standard_type(type_ptr: usize) -> bool {
    rt().standard_types.borrow().contains(&type_ptr)
}

/// Native stack to keep free for the Python code a refresh may call.
const MIN_FREE_STACK: usize = 256 * 1024;

/// Holds one level of Python's recursion budget, so a very deep graph raises
/// `RecursionError` instead of overflowing the native stack. Python 3.12 and
/// 3.13 count calls rather than measuring the stack, and worker threads have
/// small stacks, so the remaining stack is checked directly as well.
struct RecursionGuard;

impl RecursionGuard {
    fn enter(py: Python<'_>) -> PyResult<RecursionGuard> {
        if stacker::remaining_stack().is_some_and(|free| free < MIN_FREE_STACK) {
            return Err(PyRecursionError::new_err(
                "maximum recursion depth exceeded while refreshing a reactive value",
            ));
        }
        let failed = unsafe {
            pyo3::ffi::Py_EnterRecursiveCall(c" while refreshing a reactive value".as_ptr())
        };
        if failed != 0 {
            return Err(PyErr::fetch(py));
        }
        Ok(RecursionGuard)
    }
}

impl Drop for RecursionGuard {
    fn drop(&mut self) {
        unsafe { pyo3::ffi::Py_LeaveRecursiveCall() };
    }
}

// ---------------------------------------------------------------------------
// Dependency tracking
// ---------------------------------------------------------------------------

fn track_read(node: &Arc<Node>, handle: &Bound<'_, PyAny>) {
    if let Some(reader) = current_reader() {
        if !Arc::ptr_eq(&reader, node) {
            register_dependency(&reader, node, handle);
        }
    }
}

fn register_dependency(reader: &Arc<Node>, dep: &Arc<Node>, handle: &Bound<'_, PyAny>) {
    let token = reader.token.get();
    let read_version = dep.version.get();
    let mut deps = reader.deps.borrow_mut();
    if let Some(link) = deps.iter_mut().find(|link| Arc::ptr_eq(&link.node, dep)) {
        link.seen = token;
        link.read_version = read_version;
    } else {
        deps.push(DepLink {
            node: dep.clone(),
            handle: handle.clone().unbind(),
            version: NEVER,
            read_version,
            seen: token,
            active: false,
        });
    }
}

/// Subscribe to every dependency read during this refresh and drop the rest.
fn commit_refresh(reader: &Arc<Node>) {
    let token = reader.token.get();
    let mut dropped = Vec::new();
    {
        let mut deps = reader.deps.borrow_mut();
        let mut kept = Vec::with_capacity(deps.len());
        for mut link in deps.drain(..) {
            if link.seen == token {
                if !link.active {
                    link.node
                        .observers
                        .borrow_mut()
                        .push(Observer::Node(Arc::downgrade(reader)));
                    link.active = true;
                }
                link.version = link.read_version;
                kept.push(link);
            } else {
                if link.active {
                    remove_node_observer(&link.node, reader);
                }
                dropped.push(link);
            }
        }
        *deps = kept;
    }
    // Dropping a link can free its dependency, which can run Python code.
    drop(dropped);
}

fn remove_node_observer(dep: &Node, reader: &Arc<Node>) {
    let target = Arc::as_ptr(reader);
    dep.observers
        .borrow_mut()
        .retain(|observer| match observer {
            Observer::Node(weak) => weak.as_ptr() != target && weak.strong_count() > 0,
            Observer::Python(_) => true,
        });
}

fn detach_all_deps(reader: &Arc<Node>) {
    let links = std::mem::take(&mut *reader.deps.borrow_mut());
    for link in &links {
        if link.active {
            remove_node_observer(&link.node, reader);
        }
    }
    drop(links);
}

// ---------------------------------------------------------------------------
// Invalidation (push)
// ---------------------------------------------------------------------------

fn invalidate(node: &Node, force: bool) -> bool {
    let target = if force {
        State::MustRefresh
    } else {
        State::Stale
    };
    if node.state.get() < target {
        node.state.set(target);
    }
    if node.notified.get() {
        return false;
    }
    node.notified.set(true);
    true
}

/// Prune dead observers and return a snapshot that is safe to iterate while
/// Python code runs.
fn snapshot_observers(py: Python<'_>, node: &Node) -> Vec<Observer> {
    let current = std::mem::take(&mut *node.observers.borrow_mut());
    let (alive, dead): (Vec<Observer>, Vec<Observer>) = current
        .into_iter()
        .partition(|observer| observer.is_alive(py));
    let snapshot = alive
        .iter()
        .map(|observer| observer.clone_ref(py))
        .collect();
    {
        let mut observers = node.observers.borrow_mut();
        // Keep anything subscribed while the list was taken out.
        let added = std::mem::take(&mut *observers);
        *observers = alive;
        observers.extend(added);
    }
    drop(dead);
    snapshot
}

fn mark_notified(node: &Arc<Node>) -> bool {
    rt().wave.borrow_mut().insert(Arc::as_ptr(node) as usize)
}

/// Notify `start`'s observers depth-first, like the recursive Python version,
/// but with an explicit stack so long chains cannot overflow.
fn notify(py: Python<'_>, start: &Arc<Node>) -> PyResult<()> {
    // Like `_ReactiveBase.notify`, a node without observers stays out of the
    // wave, so observers added later in the wave still hear its next write.
    if start.observers.borrow().is_empty() {
        return Ok(());
    }
    if !mark_notified(start) {
        return Ok(());
    }
    let rt = rt();
    rt.wave_depth.set(rt.wave_depth.get() + 1);
    let result = notify_wave(py, start);
    let depth = rt.wave_depth.get() - 1;
    rt.wave_depth.set(depth);
    if depth == 0 {
        rt.wave.borrow_mut().clear();
    }
    result
}

fn notify_wave(py: Python<'_>, start: &Arc<Node>) -> PyResult<()> {
    let mut frames: Vec<(Vec<Observer>, usize)> = vec![(snapshot_observers(py, start), 0)];
    while let Some((observers, index)) = frames.last_mut() {
        if *index >= observers.len() {
            frames.pop();
            continue;
        }
        let observer = observers[*index].clone_ref(py);
        *index += 1;
        match observer {
            Observer::Node(weak) => {
                if let Some(node) = weak.upgrade() {
                    if invalidate(&node, false) && mark_notified(&node) {
                        let next = snapshot_observers(py, &node);
                        frames.push((next, 0));
                    }
                }
            }
            Observer::Python(reference) => {
                let target = reference.bind(py).upgrade();
                if let Some(target) = target {
                    target.call_method0(intern!(py, "update"))?;
                }
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Refresh (pull)
// ---------------------------------------------------------------------------

fn ensure_uptodate(py: Python<'_>, node: &Arc<Node>) -> PyResult<()> {
    if node.state.get() == State::Fresh {
        return Ok(());
    }
    let _guard = RecursionGuard::enter(py)?;
    // Any refresh attempt means observers must be told about the next change.
    node.notified.set(false);
    let state = node.state.get();
    if state == State::Stale && node.clock_seen.get() == clock() {
        node.state.set(State::Fresh);
        return Ok(());
    }
    if state == State::Stale && !dependencies_changed(py, node)? {
        node.state.set(State::Fresh);
        node.clock_seen.set(clock());
        return Ok(());
    }
    refresh(py, node)
}

fn dependencies_changed(py: Python<'_>, node: &Arc<Node>) -> PyResult<bool> {
    let deps: Vec<(Arc<Node>, u64)> = node
        .deps
        .borrow()
        .iter()
        .map(|link| (link.node.clone(), link.version))
        .collect();
    for (dep, seen_version) in deps {
        if dep.is_computed {
            ensure_uptodate(py, &dep)?;
        }
        if seen_version != dep.version.get() {
            return Ok(true);
        }
    }
    Ok(false)
}

fn refresh(py: Python<'_>, node: &Arc<Node>) -> PyResult<()> {
    if node.computing.get() {
        return Err(PyRuntimeError::new_err(
            "Cycle detected while evaluating Computed",
        ));
    }
    let forced = node.state.get() == State::MustRefresh;
    let had_outcome = node.state.get() != State::Uninitialized;
    let had_error = node.error.borrow().is_some();
    let compute = node
        .compute
        .borrow()
        .as_ref()
        .map(|compute| compute.clone_ref(py));
    let Some(compute) = compute else {
        return Err(PyRuntimeError::new_err(
            "Computed was cleared by the garbage collector",
        ));
    };

    node.computing.set(true);
    node.token.set(node.token.get() + 1);
    rt().frames.borrow_mut().push(Some(node.clone()));
    let result = run_compute(py, &compute);
    rt().frames.borrow_mut().pop();
    node.computing.set(false);
    // Subscribe to what this run read, even if it raised.
    commit_refresh(node);
    drop(compute);

    let (next_value, next_error) = match result {
        Ok(value) => (Some(value), None),
        Err(error) if error.is_instance_of::<PyException>(py) => (None, Some(error)),
        Err(error) => {
            // Control-flow exceptions abort evaluation instead of being cached.
            if node.state.get() < State::MustRefresh {
                node.state.set(State::MustRefresh);
            }
            return Err(error);
        }
    };

    let changed = if !had_outcome || had_error || next_error.is_some() {
        true
    } else {
        let previous = node
            .value
            .borrow()
            .as_ref()
            .map(|value| value.clone_ref(py));
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
    let old_error = node.error.replace(cached);
    node.state.set(State::Fresh);
    if changed {
        let old_value = node.value.replace(next_value);
        node.clock_seen.set(bump_version(node));
        drop(old_value);
    } else if forced {
        node.clock_seen.set(bump_version(node));
    } else {
        node.clock_seen.set(clock());
    }
    drop(old_error);
    Ok(())
}

fn run_compute(py: Python<'_>, compute: &Compute) -> PyResult<Py<PyAny>> {
    match compute {
        Compute::Function(f) => Ok(f.bind(py).call0()?.unbind()),
        Compute::Operator { func, args } => {
            let mut resolved = Vec::with_capacity(args.len());
            for arg in args {
                resolved.push(resolve_arg(py, arg.bind(py))?);
            }
            let args = PyTuple::new(py, resolved)?;
            Ok(func.bind(py).call1(args)?.unbind())
        }
    }
}

/// Unwrap one reactive boundary, like `unref`. Instances of the registered
/// public classes are read natively; any other reactive object (for example a
/// subclass that overrides `value`) goes through its Python `value` attribute.
fn resolve_arg<'py>(py: Python<'py>, arg: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    if arg.is_none()
        || arg.is_exact_instance_of::<PyFloat>()
        || arg.is_exact_instance_of::<PyInt>()
        || arg.is_exact_instance_of::<PyString>()
        || arg.is_exact_instance_of::<PyBool>()
    {
        return Ok(arg.clone());
    }
    let arg_type = arg.get_type();
    if is_standard_type(arg_type.as_ptr() as usize) {
        if let Ok(signal) = arg.cast::<SignalCore>() {
            let node = signal.borrow().node.clone();
            return read_signal(py, &node, arg);
        }
        if let Ok(computed) = arg.cast::<ComputedCore>() {
            let node = computed.borrow().node.clone();
            return read_computed(py, &node, arg);
        }
    }
    let is_reactive = match arg_type.getattr(intern!(py, "_IS_REACTIVE")) {
        Ok(flag) => flag.is_truthy()?,
        Err(_) => false,
    };
    if is_reactive {
        return arg.getattr(intern!(py, "value"));
    }
    Ok(arg.clone())
}

/// Built-in scalars compare by value (NaN equals NaN); everything else by identity.
fn has_changed(previous: &Bound<'_, PyAny>, current: &Bound<'_, PyAny>) -> PyResult<bool> {
    if previous.is(current) {
        return Ok(false);
    }
    if !previous.get_type().is(current.get_type()) {
        return Ok(true);
    }
    if previous.is_exact_instance_of::<PyFloat>() {
        let a: f64 = previous.extract()?;
        let b: f64 = current.extract()?;
        return Ok(a != b && !(a.is_nan() && b.is_nan()));
    }
    if previous.is_none()
        || previous.is_exact_instance_of::<PyInt>()
        || previous.is_exact_instance_of::<PyBool>()
        || previous.is_exact_instance_of::<PyString>()
        || previous.is_exact_instance_of::<PyBytes>()
        || previous.is_exact_instance_of::<PyComplex>()
    {
        return previous.ne(current);
    }
    Ok(true)
}

fn read_signal<'py>(
    py: Python<'py>,
    node: &Arc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    track_read(node, handle);
    Ok(raw_value(py, node))
}

fn read_computed<'py>(
    py: Python<'py>,
    node: &Arc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let refreshed = ensure_uptodate(py, node);
    // Register the read even when the refresh raises, so the reader retries.
    track_read(node, handle);
    refreshed?;
    let cached = node.error.borrow().as_ref().map(|cached| {
        (
            cached.exception.clone_ref(py),
            cached.traceback.as_ref().map(|tb| tb.clone_ref(py)),
        )
    });
    if let Some((exception, traceback)) = cached {
        let exception = exception.into_bound(py);
        // Reset the traceback so repeated reads do not accumulate frames.
        exception.setattr(intern!(py, "__traceback__"), traceback)?;
        return Err(PyErr::from_value(exception));
    }
    Ok(raw_value(py, node))
}

fn raw_value<'py>(py: Python<'py>, node: &Node) -> Bound<'py, PyAny> {
    match node.value.borrow().as_ref() {
        Some(value) => value.bind(py).clone(),
        None => py.None().into_bound(py),
    }
}

fn add_python_observer(node: &Node, observer: &Bound<'_, PyAny>) -> PyResult<()> {
    let py = observer.py();
    let existing: Vec<Py<PyWeakrefReference>> = node
        .observers
        .borrow()
        .iter()
        .filter_map(|o| match o {
            Observer::Python(reference) => Some(reference.clone_ref(py)),
            Observer::Node(_) => None,
        })
        .collect();
    for reference in &existing {
        if let Some(target) = reference.bind(py).upgrade() {
            if target.is(observer) {
                return Ok(());
            }
        }
    }
    let reference = PyWeakrefReference::new(observer)?.unbind();
    node.observers
        .borrow_mut()
        .push(Observer::Python(reference));
    Ok(())
}

fn remove_python_observer(node: &Node, observer: &Bound<'_, PyAny>) {
    let py = observer.py();
    let current = std::mem::take(&mut *node.observers.borrow_mut());
    let (removed, kept): (Vec<Observer>, Vec<Observer>) =
        current.into_iter().partition(|o| match o {
            Observer::Python(reference) => reference
                .bind(py)
                .upgrade()
                .is_some_and(|target| target.is(observer)),
            Observer::Node(_) => false,
        });
    {
        let mut observers = node.observers.borrow_mut();
        let added = std::mem::take(&mut *observers);
        *observers = kept;
        observers.extend(added);
    }
    drop(removed);
}

fn live_observer_count(py: Python<'_>, node: &Node) -> usize {
    snapshot_observers(py, node).len()
}

// ---------------------------------------------------------------------------
// Python classes
// ---------------------------------------------------------------------------

/// Base class of `signified.Signal`: mutable state.
#[pyclass(subclass, weakref, module = "signified._core", name = "Signal")]
pub struct SignalCore {
    node: Arc<Node>,
}

#[pymethods]
impl SignalCore {
    #[new]
    fn new(value: Py<PyAny>) -> Self {
        SignalCore {
            node: Arc::new(Node::new(false, Some(value), None)),
        }
    }

    #[getter]
    fn value<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        let node = slf.borrow().node.clone();
        read_signal(slf.py(), &node, slf.as_any())
    }

    #[setter]
    fn set_value(&self, py: Python<'_>, value: Py<PyAny>) -> PyResult<()> {
        let node = self.node.clone();
        let old = node.value.borrow().as_ref().map(|old| old.clone_ref(py));
        let changed = match &old {
            Some(old) => has_changed(old.bind(py), value.bind(py))?,
            None => true,
        };
        if !changed {
            return Ok(());
        }
        let previous = node.value.replace(Some(value));
        bump_version(&node);
        drop(previous);
        drop(old);
        notify(py, &node)
    }

    /// The stored value, without tracking a read.
    #[getter]
    fn _value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        raw_value(py, &self.node)
    }

    #[getter]
    fn _version(&self) -> u64 {
        self.node.version.get()
    }

    /// Notify observers unconditionally (after an in-place mutation).
    fn update(&self, py: Python<'_>) -> PyResult<()> {
        bump_version(&self.node);
        notify(py, &self.node)
    }

    fn subscribe(&self, observer: &Bound<'_, PyAny>) -> PyResult<()> {
        add_python_observer(&self.node, observer)
    }

    fn unsubscribe(&self, observer: &Bound<'_, PyAny>) {
        remove_python_observer(&self.node, observer);
    }

    fn _observer_count(&self, py: Python<'_>) -> usize {
        live_observer_count(py, &self.node)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        if let Ok(value) = self.node.value.try_borrow() {
            if let Some(value) = value.as_ref() {
                visit.call(value)?;
            }
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        let value = self.node.value.take();
        drop(value);
    }
}

/// Base class of `signified.Computed`: a lazily refreshed derived value.
#[pyclass(subclass, weakref, module = "signified._core", name = "Computed")]
pub struct ComputedCore {
    node: Arc<Node>,
}

#[pymethods]
impl ComputedCore {
    /// `Computed(f)` calls `f()`; `Computed(func, _op_args=args)` calls
    /// `func(*args)` with reactive arguments unwrapped natively.
    #[new]
    #[pyo3(signature = (f, *, _op_args = None))]
    fn new(f: Py<PyAny>, _op_args: Option<&Bound<'_, PyTuple>>) -> Self {
        let compute = match _op_args {
            Some(args) => Compute::Operator {
                func: f,
                args: args.iter().map(|arg| arg.unbind()).collect(),
            },
            None => Compute::Function(f),
        };
        ComputedCore {
            node: Arc::new(Node::new(true, None, Some(compute))),
        }
    }

    #[getter]
    fn value<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        let node = slf.borrow().node.clone();
        read_computed(slf.py(), &node, slf.as_any())
    }

    #[getter]
    fn _value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        raw_value(py, &self.node)
    }

    #[getter]
    fn _version(&self) -> u64 {
        self.node.version.get()
    }

    /// Evaluate first, so the observer sees every later upstream change.
    fn subscribe(&self, py: Python<'_>, observer: &Bound<'_, PyAny>) -> PyResult<()> {
        ensure_uptodate(py, &self.node)?;
        add_python_observer(&self.node, observer)
    }

    fn unsubscribe(&self, observer: &Bound<'_, PyAny>) {
        remove_python_observer(&self.node, observer);
    }

    fn _observer_count(&self, py: Python<'_>) -> usize {
        live_observer_count(py, &self.node)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        let node = &self.node;
        if let Ok(value) = node.value.try_borrow() {
            if let Some(value) = value.as_ref() {
                visit.call(value)?;
            }
        }
        if let Ok(compute) = node.compute.try_borrow() {
            match compute.as_ref() {
                Some(Compute::Function(f)) => visit.call(f)?,
                Some(Compute::Operator { func, args }) => {
                    visit.call(func)?;
                    for arg in args {
                        visit.call(arg)?;
                    }
                }
                None => {}
            }
        }
        if let Ok(error) = node.error.try_borrow() {
            if let Some(cached) = error.as_ref() {
                visit.call(&cached.exception)?;
                if let Some(traceback) = cached.traceback.as_ref() {
                    visit.call(traceback)?;
                }
            }
        }
        if let Ok(deps) = node.deps.try_borrow() {
            for link in deps.iter() {
                visit.call(&link.handle)?;
            }
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        let node = self.node.clone();
        detach_all_deps(&node);
        let compute = node.compute.take();
        let value = node.value.take();
        let error = node.error.take();
        drop((compute, value, error));
    }
}

// ---------------------------------------------------------------------------
// Module functions
// ---------------------------------------------------------------------------

/// Start a block whose reads do not subscribe the enclosing computation.
#[pyfunction]
fn push_untracked() {
    rt().frames.borrow_mut().push(None);
}

#[pyfunction]
fn pop_untracked() -> PyResult<()> {
    let popped = rt().frames.borrow_mut().pop();
    match popped {
        Some(None) => Ok(()),
        _ => Err(PyRuntimeError::new_err(
            "pop_untracked() without a matching push_untracked()",
        )),
    }
}

/// Register the public classes whose `value` is the engine's own getter.
#[pyfunction]
fn _register_standard_types(types: Vec<Bound<'_, PyType>>) {
    let mut standard = rt().standard_types.borrow_mut();
    for ty in types {
        standard.push(ty.as_ptr() as usize);
    }
}

#[pymodule(gil_used = true)]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SignalCore>()?;
    m.add_class::<ComputedCore>()?;
    m.add_function(wrap_pyfunction!(push_untracked, m)?)?;
    m.add_function(wrap_pyfunction!(pop_untracked, m)?)?;
    m.add_function(wrap_pyfunction!(_register_standard_types, m)?)?;
    Ok(())
}
