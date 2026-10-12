//! The reactive graph engine behind signified, independent of any language binding.
//!
//! Push invalidation, pull refresh with version checks, mark-and-sweep
//! dependency tracking, and the queue that runs effects. A [`Host`] supplies
//! everything else: what a node's value is, how a computed evaluates, how an
//! effect runs, and what an error is. Two hosts use it: the Python extension
//! (`signified._core`), whose values are Python objects, and the `signified`
//! crate, whose values are ordinary Rust types.
//!
//! The engine is generic over its host rather than calling it through trait
//! objects, so each host gets an engine compiled for its own types.
//!
//! Rules that keep the graph consistent while host code runs inside the
//! engine:
//! - Never run host code (user callbacks, destructors that can run them)
//!   while a `RefCell` in a [`Node`] or the [`Runtime`] is borrowed. Copy what
//!   you need out, release the borrow, then call or drop.
//! - Host callbacks must not unwind through the engine. A host whose user
//!   code can panic catches the panic and returns it as an error.
//! - Each thread has its own tracking frames, queue and walk depth
//!   ([`Runtime`]). Whether nodes may move between threads is the host's
//!   business: the engine itself is single-threaded (`Rc`, `Cell`).

#![forbid(unsafe_code)]

use std::fmt;
use std::rc::Rc;

pub mod effect;
pub mod invalidation;
pub mod node;
pub mod observers;
pub mod refresh;
pub mod runtime;
pub mod scheduler;
pub mod tracking;

pub use node::{ComputedState, DepLink, EffectState, Node, ReaderState, Role, State};
pub use runtime::Runtime;
pub use scheduler::Step;

/// What the engine needs from the code that embeds it.
///
/// Every method is called with nothing in the engine borrowed, so a method
/// may read and write nodes, and run user code.
pub trait Host: Sized + 'static {
    /// Passed through the engine to every host method that needs it; the
    /// Python host's is its `Python<'py>` token.
    type Cx<'a>: Copy;
    /// Data each node carries for the host, such as its value. May be unsized
    /// (a trait object), so nodes of one graph can hold different types.
    type Payload: ?Sized + 'static;
    /// What only a computed carries for the host.
    type ComputedData: Default + 'static;
    /// What only an effect carries for the host.
    type EffectData: Default + 'static;
    /// Kept in each dependency link alongside the dependency's node.
    type Handle: 'static;
    /// An observer that is not a node (the Python host's `_subscribe()`
    /// objects). A host without them uses an uninhabited type.
    type Subscriber: 'static;
    /// What a failed refresh, effect or subscriber reports.
    type Error;
    /// State a host keeps for the length of one flush of the queue.
    type FlushState: Default;

    /// Free a node's dependencies through [`runtime::release`] rather than
    /// from inside its destructor, so that freeing a long chain does not
    /// recurse. A host that sets it releases its own node references the same
    /// way.
    const DEFER_DROPS: bool = false;

    /// Run `f` with the calling thread's engine state.
    fn with_runtime<R>(f: impl FnOnce(&Runtime<Self>) -> R) -> R;

    /// Like `with_runtime`, or `None` once the thread's engine state has been
    /// destroyed (while thread-locals are torn down at thread exit). Only
    /// paths that free nodes use it.
    fn try_with_runtime<R>(f: impl FnOnce(&Runtime<Self>) -> R) -> Option<R> {
        Some(Self::with_runtime(f))
    }

    /// The version clock. By default each thread has its own; a host whose
    /// nodes can move between threads keeps one shared clock instead.
    fn clock() -> u64 {
        Self::with_runtime(|rt| rt.clock.get())
    }

    /// Advance the version clock and return its new value.
    fn bump_clock() -> u64 {
        Self::with_runtime(|rt| {
            let version = rt.clock.get() + 1;
            rt.clock.set(version);
            version
        })
    }

    /// A copy of a dependency link's handle, taken out of the link before the
    /// dependency refreshes.
    fn clone_handle(cx: Self::Cx<'_>, handle: &Self::Handle) -> Self::Handle;

    /// Run `f`, one level deeper in nested refreshes. A host bounds the depth
    /// here (or grows the stack) so that deep graphs cannot overflow it.
    fn nested<R>(
        cx: Self::Cx<'_>,
        f: impl FnOnce() -> Result<R, Self::Error>,
    ) -> Result<R, Self::Error>;

    /// Evaluate a stale computed whose dependencies changed, and record the
    /// outcome; see [`refresh`] for the steps the engine provides.
    fn refresh(
        cx: Self::Cx<'_>,
        node: &Rc<Node<Self>>,
        handle: &Self::Handle,
    ) -> Result<(), Self::Error>;

    /// Run a queued effect, usually with [`effect::run`].
    fn run_effect(cx: Self::Cx<'_>, effect: &Rc<Node<Self>>) -> Result<(), Self::Error>;

    /// A copy of a subscriber, queued during a notification walk.
    fn clone_subscriber(cx: Self::Cx<'_>, subscriber: &Self::Subscriber) -> Self::Subscriber;

    /// Identifies a queued subscriber, so it is queued once per flush.
    fn subscriber_key(subscriber: &Self::Subscriber) -> usize;

    /// Run a queued subscriber.
    fn run_subscriber(
        cx: Self::Cx<'_>,
        subscriber: Self::Subscriber,
        flush: &mut Self::FlushState,
    ) -> Step<Self::Error>;

    /// Whether `error` ends a flush at once, instead of being collected while
    /// the rest of the queue runs.
    fn is_fatal(cx: Self::Cx<'_>, error: &Self::Error) -> bool;

    /// Report the errors a flush collected (never called with none).
    fn raise_errors(cx: Self::Cx<'_>, errors: Vec<Self::Error>) -> Result<(), Self::Error>;

    /// Convert an error the engine itself detected.
    fn engine_error(error: EngineError) -> Self::Error;
}

/// An error the engine itself detects.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EngineError {
    /// A computed read itself while evaluating.
    Cycle,
    /// A computed is being evaluated on another thread.
    OtherThread,
    /// A computation or effect left an untracked block open.
    UnbalancedFrames,
    /// An untracked block was exited without being entered.
    UntrackedExitWithoutEnter,
    /// An effect kept queuing itself.
    EffectDidNotSettle,
}

impl fmt::Display for EngineError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            EngineError::Cycle => "Cycle detected while evaluating Computed",
            EngineError::OtherThread => "Computed is being evaluated on another thread",
            EngineError::UnbalancedFrames => {
                "tracking frames are unbalanced: an untracked() block was left open inside a \
                 computation or effect"
            }
            EngineError::UntrackedExitWithoutEnter => "untracked() exited without a matching enter",
            EngineError::EffectDidNotSettle => "Effect did not settle after 100 runs",
        })
    }
}

impl std::error::Error for EngineError {}
