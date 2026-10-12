//! Each thread's engine state, and versions.

use std::cell::Cell;

use crate::node::Node;
use crate::scheduler::Queue;
use crate::tracking::Frames;
use crate::Host;

/// One thread's engine state. The tracking frames and the queue each belong
/// to one module, which alone can see inside them. Threads track, batch and
/// run effects independently, so graphs used on different threads do not see
/// each other's evaluations or batches.
///
/// A host keeps one per thread, in a `thread_local!`, and hands it out from
/// [`Host::with_runtime`].
pub struct Runtime<H: Host> {
    /// Nesting of this thread's notification walks; its effects run when it
    /// returns to zero.
    pub(crate) wave_depth: Cell<u32>,
    pub(crate) frames: Frames<H>,
    pub(crate) queue: Queue<H>,
    /// The version clock, for hosts that keep one per thread (the default
    /// [`Host::clock`]).
    pub clock: Cell<u64>,
}

impl<H: Host> Default for Runtime<H> {
    fn default() -> Self {
        Runtime {
            wave_depth: Cell::new(0),
            frames: Frames::default(),
            queue: Queue::default(),
            clock: Cell::new(0),
        }
    }
}

/// Advance the clock and stamp `node` with the new version. Versions are
/// unique across a clock's nodes and never reused.
pub fn bump_version<H: Host, P: ?Sized>(node: &Node<H, P>) -> u64 {
    let version = H::bump_clock();
    node.version.set(version);
    version
}
