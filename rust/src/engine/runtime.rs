//! Each thread's engine state, and the version clock all threads share.

use std::cell::Cell;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::engine::node::Node;
use crate::engine::sampling::Substitutions;
use crate::engine::scheduler::Queue;
use crate::engine::tracking::Frames;

/// One thread's engine state. The tracking frames and the queue each belong
/// to one module, which alone can see inside them. Threads track, batch and
/// run effects independently, so graphs used on different threads do not see
/// each other's evaluations or batches.
pub(crate) struct Runtime {
    /// Nesting of this thread's notification walks; its effects run when it
    /// returns to zero.
    pub(crate) wave_depth: Cell<u32>,
    pub(crate) frames: Frames,
    pub(crate) queue: Queue,
    pub(crate) substitutions: Substitutions,
}

thread_local! {
    // Initialized in a `const`, so each access skips a lazy-initialization check.
    static RUNTIME: Runtime = const {
        Runtime {
            wave_depth: Cell::new(0),
            frames: Frames::new(),
            queue: Queue::new(),
            substitutions: Substitutions::new(),
        }
    };
}

/// Run `f` with the calling thread's engine state.
pub(crate) fn with_rt<R>(f: impl FnOnce(&Runtime) -> R) -> R {
    RUNTIME.with(f)
}

/// Shared by all threads, so versions stay unique when a graph moves from one
/// thread to another. The GIL serializes access, so a plain load and store
/// suffice.
static CLOCK: AtomicU64 = AtomicU64::new(0);

pub(crate) fn clock() -> u64 {
    CLOCK.load(Ordering::Relaxed)
}

/// Advance the global version clock.
pub(crate) fn bump_clock() -> u64 {
    let version = CLOCK.load(Ordering::Relaxed) + 1;
    CLOCK.store(version, Ordering::Relaxed);
    version
}

/// Advance the clock and stamp `node` with the new version. Versions are
/// unique across nodes and never reused.
pub(crate) fn bump_version(node: &Node) -> u64 {
    let version = bump_clock();
    node.version.set(version);
    version
}
