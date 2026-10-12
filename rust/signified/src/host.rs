//! The engine's Rust host: each node's payload is a typed slot behind a trait
//! object, and a failure is a caught panic (or an error the engine detected).

use std::any::Any;
use std::panic::{self, AssertUnwindSafe};
use std::rc::Rc;

use signified_engine::{runtime, scheduler, EngineError, Host, Runtime, Step};

/// A node of the Rust host.
pub(crate) type Node = signified_engine::Node<Native>;

pub(crate) struct Native;

/// Rust graphs have no subscribers other than nodes.
pub(crate) enum Never {}

/// Why a refresh or an effect failed.
pub(crate) enum Error {
    /// User code panicked; the payload is resumed where the value was asked
    /// for.
    Panic(Box<dyn Any + Send>),
    /// The engine found a cycle or similar misuse.
    Engine(EngineError),
}

/// Stack kept free below each nested refresh; when less is left, the refresh
/// continues on a new segment of `NEW_SEGMENT` bytes.
const RED_ZONE: usize = 64 * 1024;
const NEW_SEGMENT: usize = 1024 * 1024;

thread_local! {
    static RUNTIME: Runtime<Native> = Runtime::default();
}

/// What the engine reaches through a node's payload.
pub(crate) trait Slot: 'static {
    /// The cell holding the value: `RefCell<T>` for a signal,
    /// `RefCell<Option<T>>` for a computed.
    fn cell(&self) -> &dyn Any;

    /// Evaluate the computed whose payload this is (`node`), and record the
    /// outcome.
    fn refresh(&self, node: &Rc<Node>) -> Result<(), Error>;

    /// Call the effect function whose payload this is.
    fn call(&self) -> Result<(), Error>;
}

/// A handle's reference to its node. It is let go through the engine, so
/// freeing a long chain of nodes, each holding a handle to the one before,
/// does not recurse.
pub(crate) struct Owned(Option<Rc<Node>>);

impl Owned {
    pub(crate) fn new(node: Rc<Node>) -> Owned {
        Owned(Some(node))
    }

    #[inline]
    pub(crate) fn rc(&self) -> &Rc<Node> {
        self.0
            .as_ref()
            .expect("a handle holds its node until it is dropped")
    }
}

impl Clone for Owned {
    fn clone(&self) -> Self {
        Owned(self.0.clone())
    }
}

impl Drop for Owned {
    fn drop(&mut self) {
        if let Some(node) = self.0.take() {
            runtime::release(node);
        }
    }
}

/// Run user code, turning a panic into an error so the engine can finish its
/// bookkeeping before the panic continues.
pub(crate) fn catch<R>(f: impl FnOnce() -> R) -> Result<R, Error> {
    panic::catch_unwind(AssertUnwindSafe(f)).map_err(Error::Panic)
}

/// Continue a failure where a value was asked for: resume a caught panic, or
/// panic with the engine's message.
pub(crate) fn raise(error: Error) -> ! {
    match error {
        Error::Panic(payload) => panic::resume_unwind(payload),
        Error::Engine(error) => panic!("{error}"),
    }
}

/// `result`'s value, or its failure continued.
pub(crate) fn unwrap<T>(result: Result<T, Error>) -> T {
    result.unwrap_or_else(|error| raise(error))
}

impl Host for Native {
    type Cx<'a> = ();
    type Payload = dyn Slot;
    type ComputedData = ();
    type EffectData = ();
    type Handle = ();
    type Subscriber = Never;
    type Error = Error;
    type FlushState = ();

    /// Rust handles own their nodes outright, so freeing a long chain would
    /// otherwise recurse once per node.
    const DEFER_DROPS: bool = true;

    #[inline]
    fn with_runtime<R>(f: impl FnOnce(&Runtime<Self>) -> R) -> R {
        RUNTIME.with(f)
    }

    /// Nodes kept in other thread-locals can be freed after this one is.
    fn try_with_runtime<R>(f: impl FnOnce(&Runtime<Self>) -> R) -> Option<R> {
        RUNTIME.try_with(f).ok()
    }

    #[inline]
    fn clone_handle(_: (), _: &()) {}

    #[inline]
    fn nested<R>(_: (), f: impl FnOnce() -> Result<R, Error>) -> Result<R, Error> {
        stacker::maybe_grow(RED_ZONE, NEW_SEGMENT, f)
    }

    fn refresh(_: (), node: &Rc<Node>, _: &()) -> Result<(), Error> {
        node.payload.refresh(node)
    }

    fn run_effect(_: (), effect: &Rc<Node>) -> Result<(), Error> {
        signified_engine::effect::run((), effect, || Some(()), |_| effect.payload.call())
    }

    fn clone_subscriber(_: (), subscriber: &Never) -> Never {
        match *subscriber {}
    }

    fn subscriber_key(subscriber: &Never) -> usize {
        match *subscriber {}
    }

    fn run_subscriber(_: (), subscriber: Never, _: &mut ()) -> Step<Error> {
        match subscriber {}
    }

    /// A failed effect does not stop the others; the first failure is raised
    /// once the queue has run.
    fn is_fatal(_: (), _: &Error) -> bool {
        false
    }

    fn raise_errors(_: (), mut errors: Vec<Error>) -> Result<(), Error> {
        // The others' panic messages were already printed when they panicked.
        Err(errors.swap_remove(0))
    }

    fn engine_error(error: EngineError) -> Error {
        Error::Engine(error)
    }
}

/// Defer effects until the outermost batch ends, even if `f` panics.
pub(crate) fn batch<R>(f: impl FnOnce() -> R) -> R {
    struct Ending;

    impl Drop for Ending {
        /// Only reached while `f` unwinds: end the batch without running
        /// effects, which could panic again. They run at the next flush.
        fn drop(&mut self) {
            scheduler::leave_batch::<Native>();
        }
    }

    scheduler::begin_batch::<Native>();
    let ending = Ending;
    let result = f();
    std::mem::forget(ending);
    unwrap(scheduler::end_batch::<Native>(()));
    result
}
