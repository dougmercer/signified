//! The engine's Python host: values, handles and errors are Python objects.

use std::num::NonZeroU64;
use std::rc::Rc;
use std::sync::atomic::{AtomicU64, Ordering};

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyWeakrefReference;
use signified_engine::{Counter, EngineError, Host, Runtime, Step};

use crate::effect;
use crate::node::{Node, PyComputed, PyEffect, PySlot};
use crate::refresh::{self, RecursionGuard};
use crate::scheduler::{self, ObserverRuns};

pub(crate) struct PyHost;

thread_local! {
    static RUNTIME: Runtime<PyHost> = const { Runtime::new() };
}

/// Shared by all threads, so versions stay unique when a graph moves from one
/// thread to another. The GIL serializes access, so a plain load and store
/// suffice.
static CLOCK: AtomicU64 = AtomicU64::new(0);

/// The engine's other counters (`Counter`), shared for the same reason.
static NUMBERS: [AtomicU64; 2] = [AtomicU64::new(0), AtomicU64::new(0)];

impl Host for PyHost {
    type Cx<'py> = Python<'py>;
    type Payload = PySlot;
    type ComputedData = PyComputed;
    type EffectData = PyEffect;
    /// The dependency's Python object; keeps it alive and is visible to the GC.
    type Handle = Py<PyAny>;
    /// A `_subscribe()` observer's weak reference.
    type Subscriber = Py<PyWeakrefReference>;
    type Error = PyErr;
    type FlushState = ObserverRuns;

    #[inline]
    fn with_runtime<R>(f: impl FnOnce(&Runtime<Self>) -> R) -> R {
        RUNTIME.with(f)
    }

    #[inline]
    fn clock() -> u64 {
        CLOCK.load(Ordering::Relaxed)
    }

    #[inline]
    fn bump_clock() -> u64 {
        let version = CLOCK.load(Ordering::Relaxed) + 1;
        CLOCK.store(version, Ordering::Relaxed);
        version
    }

    #[inline]
    fn next_number(counter: Counter) -> NonZeroU64 {
        let counter = &NUMBERS[counter as usize];
        let number = NonZeroU64::MIN.saturating_add(counter.load(Ordering::Relaxed));
        counter.store(number.get(), Ordering::Relaxed);
        number
    }

    #[inline]
    fn clone_handle(py: Python<'_>, handle: &Py<PyAny>) -> Py<PyAny> {
        handle.clone_ref(py)
    }

    #[inline]
    fn nested<R>(py: Python<'_>, f: impl FnOnce() -> PyResult<R>) -> PyResult<R> {
        let _guard = RecursionGuard::enter(py)?;
        f()
    }

    fn refresh(py: Python<'_>, node: &Rc<Node>, handle: &Py<PyAny>) -> PyResult<()> {
        refresh::refresh(py, node, handle.bind(py))
    }

    fn run_effect(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
        effect::run(py, effect)
    }

    fn clone_subscriber(
        py: Python<'_>,
        subscriber: &Py<PyWeakrefReference>,
    ) -> Py<PyWeakrefReference> {
        subscriber.clone_ref(py)
    }

    fn subscriber_key(subscriber: &Py<PyWeakrefReference>) -> usize {
        subscriber.as_ptr() as usize
    }

    fn run_subscriber(
        py: Python<'_>,
        subscriber: Py<PyWeakrefReference>,
        runs: &mut ObserverRuns,
    ) -> Step<PyErr> {
        scheduler::run_observer(py, subscriber, runs)
    }

    fn is_fatal(py: Python<'_>, error: &PyErr) -> bool {
        !error.is_instance_of::<PyException>(py)
    }

    fn raise_errors(py: Python<'_>, errors: Vec<PyErr>) -> PyResult<()> {
        scheduler::raise_errors(py, errors)
    }

    fn engine_error(error: EngineError) -> PyErr {
        PyRuntimeError::new_err(error.to_string())
    }
}
