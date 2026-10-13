//! The queue of effects and `_subscribe()` observers waiting to run, and
//! batches. Both kinds of work are queued during a notification walk and run,
//! in the order they were queued, once the outermost walk or batch ends.

use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet, VecDeque};
use std::hash::{BuildHasherDefault, DefaultHasher};
use std::num::NonZeroU64;
use std::rc::{Rc, Weak};
use std::sync::atomic::{AtomicU64, Ordering};

use pyo3::exceptions::{PyException, PyRuntimeError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyWeakrefReference};

use crate::engine::node::Node;
use crate::engine::runtime::with_rt;

const MAX_RUNS: u32 = 100;

/// Work waiting in the queue.
enum Job {
    /// An effect, valid while its `queued` number is still `seq`.
    Effect { node: Weak<Node>, seq: NonZeroU64 },
    /// A `_subscribe()` observer's weak reference; its `update()` is called.
    Observer(Py<PyWeakrefReference>),
}

/// The work a thread has waiting to run, and the state of the flush that
/// runs it. Part of the runtime.
pub(crate) struct Queue {
    /// Effects and observers waiting to run, in the order they were queued.
    pending: RefCell<VecDeque<Job>>,
    /// Weak references of observers waiting in `pending`. A queued observer
    /// whose reference is missing was unsubscribed and is skipped. (A fixed
    /// hasher, so the queue can be built in a `const fn`.)
    queued_observers: RefCell<HashSet<usize, BuildHasherDefault<DefaultHasher>>>,
    batch_depth: Cell<u32>,
    flushing: Cell<bool>,
}

impl Queue {
    pub(crate) const fn new() -> Queue {
        Queue {
            pending: RefCell::new(VecDeque::new()),
            queued_observers: RefCell::new(HashSet::with_hasher(BuildHasherDefault::new())),
            batch_depth: Cell::new(0),
            flushing: Cell::new(false),
        }
    }
}

/// A thread can exit inside a `batch()` it never closed. Its queued work is
/// leaked: freeing it then would touch nodes without holding the GIL.
impl Drop for Queue {
    fn drop(&mut self) {
        std::mem::forget(std::mem::take(self.pending.get_mut()));
    }
}

fn with_queue<R>(f: impl FnOnce(&Queue) -> R) -> R {
    with_rt(|rt| f(&rt.queue))
}

/// Numbers queued effects and flushes. Shared by all threads, so a number is
/// never reused for another queuing or flush, wherever it happens. The GIL
/// serializes access, so a plain load and store suffice.
static PENDING_SEQ: AtomicU64 = AtomicU64::new(0);
static FLUSH_EPOCH: AtomicU64 = AtomicU64::new(0);

fn next_number(counter: &AtomicU64) -> NonZeroU64 {
    let number = NonZeroU64::MIN.saturating_add(counter.load(Ordering::Relaxed));
    counter.store(number.get(), Ordering::Relaxed);
    number
}

/// Marks a flush in progress while it lives, so a panic that unwinds through
/// a flush cannot leave the mark set and block every later flush.
struct Flushing<'a>(&'a Queue);

impl Flushing<'_> {
    fn start(queue: &Queue) -> Flushing<'_> {
        queue.flushing.set(true);
        Flushing(queue)
    }
}

impl Drop for Flushing<'_> {
    fn drop(&mut self) {
        self.0.flushing.set(false);
    }
}

/// Queue `effect` unless it is disposed or already queued.
pub(crate) fn enqueue_effect(effect: &Rc<Node>) {
    let state = effect.effect_state();
    if !state.active.get() || state.queued.get().is_some() {
        return;
    }
    let seq = next_number(&PENDING_SEQ);
    state.queued.set(Some(seq));
    with_queue(|queue| {
        queue.pending.borrow_mut().push_back(Job::Effect {
            node: Rc::downgrade(effect),
            seq,
        })
    });
}

/// Queue a `_subscribe()` observer unless it is already queued.
pub(crate) fn enqueue_observer(reference: Py<PyWeakrefReference>) {
    with_queue(|queue| {
        let fresh = queue
            .queued_observers
            .borrow_mut()
            .insert(reference.as_ptr() as usize);
        if fresh {
            queue
                .pending
                .borrow_mut()
                .push_back(Job::Observer(reference));
        }
    })
}

/// Cancel a queued call of the observer whose weak reference is `reference`.
pub(crate) fn cancel_observer(reference: usize) {
    with_queue(|queue| queue.queued_observers.borrow_mut().remove(&reference));
}

/// Queue `effect`, then run the queue unless a walk, batch or flush is in
/// progress.
pub(crate) fn schedule(py: Python<'_>, effect: &Rc<Node>) -> PyResult<()> {
    enqueue_effect(effect);
    flush(py)
}

/// Drop a queued run of `effect`, if any.
pub(crate) fn discard(effect: &Node) {
    effect.effect_state().queued.set(None);
}

/// Run queued work in order. One failure is raised directly and several as an
/// `ExceptionGroup`. Something that keeps queuing itself stops the flush after
/// `MAX_RUNS` runs.
pub(crate) fn flush(py: Python<'_>) -> PyResult<()> {
    with_rt(|rt| {
        let queue = &rt.queue;
        if queue.pending.borrow().is_empty()
            || queue.flushing.get()
            || queue.batch_depth.get() > 0
            || rt.wave_depth.get() > 0
        {
            return Ok(());
        }
        let flushing = Flushing::start(queue);
        let epoch = next_number(&FLUSH_EPOCH).get();
        let mut errors = Vec::new();
        // Runs per observer, keyed by its address and checked against a weak
        // reference to it.
        let mut observer_runs: HashMap<usize, (Py<PyWeakrefReference>, u32)> = HashMap::new();
        let outcome = run_pending(py, queue, epoch, &mut observer_runs, &mut errors);
        // Whatever is left was abandoned by an error.
        let abandoned = std::mem::take(&mut *queue.pending.borrow_mut());
        queue.queued_observers.borrow_mut().clear();
        for job in &abandoned {
            if let Job::Effect { node, seq } = job {
                if let Some(effect) = node.upgrade() {
                    if effect.effect_state().queued.get() == Some(*seq) {
                        effect.effect_state().queued.set(None);
                    }
                }
            }
        }
        drop(flushing);
        drop(abandoned);
        drop(observer_runs);
        outcome?;
        raise_errors(py, errors)
    })
}

fn run_pending(
    py: Python<'_>,
    queue: &Queue,
    epoch: u64,
    observer_runs: &mut HashMap<usize, (Py<PyWeakrefReference>, u32)>,
    errors: &mut Vec<PyErr>,
) -> PyResult<()> {
    loop {
        let job = queue.pending.borrow_mut().pop_front();
        let Some(job) = job else {
            return Ok(());
        };
        let outcome = match job {
            Job::Effect { node, seq } => {
                let Some(effect) = node.upgrade() else {
                    continue;
                };
                let state = effect.effect_state();
                // Discarded, or queued again since.
                if state.queued.get() != Some(seq) {
                    continue;
                }
                state.queued.set(None);
                if !state.active.get() {
                    continue;
                }
                if state.run_epoch.get() != epoch {
                    state.run_epoch.set(epoch);
                    state.runs.set(0);
                }
                state.runs.set(state.runs.get() + 1);
                if state.runs.get() > MAX_RUNS {
                    errors.push(PyRuntimeError::new_err(format!(
                        "Effect did not settle after {MAX_RUNS} runs"
                    )));
                    return Ok(());
                }
                crate::engine::effect::run(py, &effect)
            }
            Job::Observer(reference) => {
                let key = reference.as_ptr() as usize;
                // Unsubscribed since it was queued.
                if !queue.queued_observers.borrow_mut().remove(&key) {
                    continue;
                }
                let Some(target) = reference.bind(py).upgrade() else {
                    continue;
                };
                // Count runs per observer, not per subscription, so an observer
                // that resubscribes itself still reaches the limit. The entry
                // keeps a weak reference to its observer: one whose observer
                // died, and whose address was reused, starts over.
                let entry = observer_runs
                    .entry(target.as_ptr() as usize)
                    .or_insert_with(|| (reference.clone_ref(py), 0));
                let same_observer = entry
                    .0
                    .bind(py)
                    .upgrade()
                    .is_some_and(|seen| seen.is(&target));
                if !same_observer {
                    *entry = (reference.clone_ref(py), 0);
                }
                entry.1 += 1;
                if entry.1 > MAX_RUNS {
                    errors.push(PyRuntimeError::new_err(format!(
                        "Observer did not settle after {MAX_RUNS} runs"
                    )));
                    return Ok(());
                }
                target.call_method0(intern!(py, "update")).map(drop)
            }
        };
        match outcome {
            Ok(()) => {}
            Err(error) if error.is_instance_of::<PyException>(py) => errors.push(error),
            Err(error) => return Err(error),
        }
    }
}

fn raise_errors(py: Python<'_>, mut errors: Vec<PyErr>) -> PyResult<()> {
    match errors.len() {
        0 => Ok(()),
        1 => Err(errors.remove(0)),
        _ => {
            let exceptions = PyList::new(py, errors.into_iter().map(|error| error.into_value(py)))?;
            let group = py
                .import(intern!(py, "builtins"))?
                .getattr(intern!(py, "ExceptionGroup"))?
                .call1(("Signified effect failures", exceptions))?;
            Err(PyErr::from_value(group))
        }
    }
}

/// Defer effects and observers until the matching `end_batch`.
pub(crate) fn begin_batch() {
    with_queue(|queue| queue.batch_depth.set(queue.batch_depth.get() + 1));
}

/// End a batch; the outermost one runs the queue.
pub(crate) fn end_batch(py: Python<'_>) -> PyResult<()> {
    with_queue(|queue| {
        queue
            .batch_depth
            .set(queue.batch_depth.get().saturating_sub(1))
    });
    flush(py)
}
