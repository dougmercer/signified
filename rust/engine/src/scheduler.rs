//! The queue of effects and subscribers waiting to run, and batches. Both
//! kinds of work are queued during a notification walk and run, in the order
//! they were queued, once the outermost walk or batch ends.

use std::cell::{Cell, RefCell};
use std::collections::{HashSet, VecDeque};
use std::num::NonZeroU64;
use std::rc::{Rc, Weak};
use std::sync::atomic::{AtomicU64, Ordering};

use crate::node::Node;
use crate::{EngineError, Host};

/// Runs allowed per effect (and, for hosts that count them, per subscriber)
/// in one flush.
pub const MAX_RUNS: u32 = 100;

/// What running one subscriber did.
pub enum Step<E> {
    /// It ran, or had nothing to run.
    Done,
    /// It failed. The error ends the flush if it is fatal, and is otherwise
    /// collected while the rest of the queue runs.
    Failed(E),
    /// It ran too often in this flush: report `E` and stop flushing.
    Stop(E),
}

/// Work waiting in the queue.
enum Job<H: Host> {
    /// An effect, valid while its `queued` number is still `seq`.
    Effect {
        node: Weak<Node<H>>,
        seq: NonZeroU64,
    },
    Subscriber(H::Subscriber),
}

/// The work a thread has waiting to run, and the state of the flush that
/// runs it. Part of the runtime.
pub(crate) struct Queue<H: Host> {
    /// Effects and subscribers waiting to run, in the order they were queued.
    pending: RefCell<VecDeque<Job<H>>>,
    /// Keys of subscribers waiting in `pending`. A queued subscriber whose
    /// key is missing was unsubscribed and is skipped.
    queued_subscribers: RefCell<HashSet<usize>>,
    batch_depth: Cell<u32>,
    flushing: Cell<bool>,
}

impl<H: Host> Default for Queue<H> {
    fn default() -> Self {
        Queue {
            pending: RefCell::new(VecDeque::new()),
            queued_subscribers: RefCell::new(HashSet::new()),
            batch_depth: Cell::new(0),
            flushing: Cell::new(false),
        }
    }
}

/// A thread can exit inside a batch it never closed. Its queued work is
/// leaked: a host whose nodes move between threads (Python's) could not free
/// it safely from a thread-exit destructor.
impl<H: Host> Drop for Queue<H> {
    fn drop(&mut self) {
        std::mem::forget(std::mem::take(self.pending.get_mut()));
    }
}

fn with_queue<H: Host, R>(f: impl FnOnce(&Queue<H>) -> R) -> R {
    H::with_runtime(|rt| f(&rt.queue))
}

/// Numbers queued effects and flushes. Shared by all threads, so a number is
/// never reused for another queuing or flush, wherever it happens.
static PENDING_SEQ: AtomicU64 = AtomicU64::new(1);
static FLUSH_EPOCH: AtomicU64 = AtomicU64::new(1);

fn next_number(counter: &AtomicU64) -> NonZeroU64 {
    NonZeroU64::new(counter.fetch_add(1, Ordering::Relaxed)).unwrap_or(NonZeroU64::MAX)
}

/// Marks a flush in progress while it lives, so a panic that unwinds through
/// a flush cannot leave the mark set and block every later flush.
struct Flushing<'a, H: Host>(&'a Queue<H>);

impl<H: Host> Flushing<'_, H> {
    fn start(queue: &Queue<H>) -> Flushing<'_, H> {
        queue.flushing.set(true);
        Flushing(queue)
    }
}

impl<H: Host> Drop for Flushing<'_, H> {
    fn drop(&mut self) {
        self.0.flushing.set(false);
    }
}

/// Queue `effect` unless it is disposed or already queued.
pub fn enqueue_effect<H: Host>(effect: &Rc<Node<H>>) {
    let state = effect.effect_state();
    if !state.active.get() || state.queued.get().is_some() {
        return;
    }
    let seq = next_number(&PENDING_SEQ);
    state.queued.set(Some(seq));
    with_queue::<H, _>(|queue| {
        queue.pending.borrow_mut().push_back(Job::Effect {
            node: Rc::downgrade(effect),
            seq,
        })
    });
}

/// Queue a subscriber unless it is already queued.
pub fn enqueue_subscriber<H: Host>(subscriber: H::Subscriber) {
    let key = H::subscriber_key(&subscriber);
    let fresh = with_queue::<H, _>(|queue| queue.queued_subscribers.borrow_mut().insert(key));
    if fresh {
        with_queue::<H, _>(|queue| {
            queue
                .pending
                .borrow_mut()
                .push_back(Job::Subscriber(subscriber))
        });
    }
}

/// Cancel a queued run of the subscriber with this key.
pub fn cancel_subscriber<H: Host>(key: usize) {
    with_queue::<H, _>(|queue| queue.queued_subscribers.borrow_mut().remove(&key));
}

/// Queue `effect`, then run the queue unless a walk, batch or flush is in
/// progress.
pub fn schedule<H: Host>(cx: H::Cx<'_>, effect: &Rc<Node<H>>) -> Result<(), H::Error> {
    enqueue_effect(effect);
    flush::<H>(cx)
}

/// Drop a queued run of `effect`, if any.
pub fn discard<H: Host>(effect: &Node<H>) {
    effect.effect_state().queued.set(None);
}

/// Defer effects and subscribers until the matching `end_batch`.
pub fn begin_batch<H: Host>() {
    with_queue::<H, _>(|queue| queue.batch_depth.set(queue.batch_depth.get() + 1));
}

/// End a batch; the outermost one runs the queue.
pub fn end_batch<H: Host>(cx: H::Cx<'_>) -> Result<(), H::Error> {
    leave_batch::<H>();
    flush::<H>(cx)
}

/// End a batch without running the queue; what it deferred runs at the next
/// flush.
pub fn leave_batch<H: Host>() {
    with_queue::<H, _>(|queue| {
        queue
            .batch_depth
            .set(queue.batch_depth.get().saturating_sub(1))
    });
}

/// Run queued work in order. Errors are collected and reported together by
/// the host; a fatal one ends the flush at once. Something that keeps
/// queuing itself stops the flush after `MAX_RUNS` runs.
pub fn flush<H: Host>(cx: H::Cx<'_>) -> Result<(), H::Error> {
    H::with_runtime(|rt| {
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
        let mut state = H::FlushState::default();
        let outcome = run_pending(cx, queue, epoch, &mut state, &mut errors);
        // Whatever is left was abandoned by an error.
        let abandoned = std::mem::take(&mut *queue.pending.borrow_mut());
        queue.queued_subscribers.borrow_mut().clear();
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
        drop(state);
        outcome?;
        if errors.is_empty() {
            return Ok(());
        }
        H::raise_errors(cx, errors)
    })
}

fn run_pending<H: Host>(
    cx: H::Cx<'_>,
    queue: &Queue<H>,
    epoch: u64,
    state: &mut H::FlushState,
    errors: &mut Vec<H::Error>,
) -> Result<(), H::Error> {
    loop {
        let job = queue.pending.borrow_mut().pop_front();
        let Some(job) = job else {
            return Ok(());
        };
        let step = match job {
            Job::Effect { node, seq } => {
                let Some(effect) = node.upgrade() else {
                    continue;
                };
                let effect_state = effect.effect_state();
                // Discarded, or queued again since.
                if effect_state.queued.get() != Some(seq) {
                    continue;
                }
                effect_state.queued.set(None);
                if !effect_state.active.get() {
                    continue;
                }
                if effect_state.run_epoch.get() != epoch {
                    effect_state.run_epoch.set(epoch);
                    effect_state.runs.set(0);
                }
                effect_state.runs.set(effect_state.runs.get() + 1);
                if effect_state.runs.get() > MAX_RUNS {
                    Step::Stop(H::engine_error(EngineError::EffectDidNotSettle))
                } else {
                    match H::run_effect(cx, &effect) {
                        Ok(()) => Step::Done,
                        Err(error) => Step::Failed(error),
                    }
                }
            }
            Job::Subscriber(subscriber) => {
                // Unsubscribed since it was queued.
                let key = H::subscriber_key(&subscriber);
                if !queue.queued_subscribers.borrow_mut().remove(&key) {
                    continue;
                }
                H::run_subscriber(cx, subscriber, state)
            }
        };
        match step {
            Step::Done => {}
            Step::Failed(error) if H::is_fatal(cx, &error) => return Err(error),
            Step::Failed(error) => errors.push(error),
            Step::Stop(error) => {
                errors.push(error);
                return Ok(());
            }
        }
    }
}
