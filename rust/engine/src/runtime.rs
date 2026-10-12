//! Each thread's engine state, and versions.

use std::cell::{Cell, RefCell};
use std::marker::PhantomData;
use std::rc::Rc;

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
    /// The last number of each [`Counter`](crate::Counter), for hosts that
    /// keep them per thread (the default [`Host::next_number`]).
    pub numbers: [Cell<u64>; 2],
    /// Nodes released while another release was freeing ([`release`]), and
    /// whether one further up this thread's stack is freeing them.
    pub(crate) freeing: RefCell<Vec<Rc<Node<H>>>>,
    pub(crate) draining: Cell<bool>,
}

impl<H: Host> Runtime<H> {
    /// Empty engine state. A `const fn`, so a host can declare its
    /// thread-local as `const { Runtime::new() }`, which skips a lazy
    /// initialization check on every access.
    pub const fn new() -> Self {
        Runtime {
            wave_depth: Cell::new(0),
            frames: Frames::new(),
            queue: Queue::new(),
            clock: Cell::new(0),
            numbers: [Cell::new(0), Cell::new(0)],
            freeing: RefCell::new(Vec::new()),
            draining: Cell::new(false),
        }
    }
}

impl<H: Host> Default for Runtime<H> {
    fn default() -> Self {
        Runtime::new()
    }
}

/// Advance the clock and stamp `node` with the new version. Versions are
/// unique across a clock's nodes and never reused.
pub fn bump_version<H: Host, P: ?Sized>(node: &Node<H, P>) -> u64 {
    let version = H::bump_clock();
    node.version.set(version);
    version
}

/// Let go of `node`, for [`Host::DEFER_DROPS`]. If that frees it, nodes it
/// releases in turn (its dependencies, and whatever its payload held) are
/// queued and freed one at a time by the outermost call, so freeing a chain
/// takes constant stack.
pub fn release<H: Host>(node: Rc<Node<H>>) {
    let mut node = Some(node);
    let outermost = H::try_with_runtime(|rt| {
        if rt.draining.get() {
            rt.freeing.borrow_mut().extend(node.take());
            return false;
        }
        rt.draining.set(true);
        true
    });
    // Without engine state (thread exit), it is freed here.
    drop(node);
    if outermost != Some(true) {
        return;
    }

    /// Clears `draining` even if a destructor panics; what is left is freed
    /// by the next outermost call.
    struct Draining<H: Host>(PhantomData<H>);

    impl<H: Host> Drop for Draining<H> {
        fn drop(&mut self) {
            H::try_with_runtime(|rt| rt.draining.set(false));
        }
    }

    let _draining = Draining::<H>(PhantomData);
    while let Some(next) = H::try_with_runtime(|rt| rt.freeing.borrow_mut().pop()).flatten() {
        drop(next);
    }
}
