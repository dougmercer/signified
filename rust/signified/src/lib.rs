//! Reactive values for Rust: signals, computeds and effects, on the engine of
//! the Python library [signified](https://github.com/dougmercer/signified).
//!
//! - A [`Signal`] holds a value you set.
//! - A [`Computed`] derives a value from signals and other computeds. It is
//!   lazy: it runs when read, and only if something it read changed.
//! - An [`Effect`] runs a function again whenever something it read changes.
//!
//! Dependencies are whatever a computed or effect read on its last run;
//! nothing is declared up front.
//!
//! ```
//! use signified::{Computed, Signal};
//!
//! let first = Signal::new("Ada".to_string());
//! let last = Signal::new("Lovelace".to_string());
//! let full = Computed::new({
//!     let (first, last) = (first.clone(), last.clone());
//!     move || format!("{} {}", first.get(), last.get())
//! });
//! assert_eq!(full.get(), "Ada Lovelace");
//! last.set("Byron".to_string());
//! assert_eq!(full.get(), "Ada Byron");
//! ```
//!
//! # Threads
//!
//! Reactive values belong to the thread that made them: handles are neither
//! `Send` nor `Sync`. Each thread has its own graph.
//!
//! ```compile_fail
//! fn send<T: Send>(_: T) {}
//! send(signified::Signal::new(1));
//! ```
//!
//! # Panics
//!
//! A panic in a computed's function or an effect is caught, the graph is put
//! back in order, and the panic continues where the value was read or the
//! write that ran the effect happened. Reading a computed while it computes
//! (a cycle) panics.
//!
//! # Memory
//!
//! Handles are reference counted. A computed or effect keeps what it read
//! alive; what it read does not keep it alive. A value that holds a handle to
//! a computed that reads it is a reference cycle and is never freed.

#![forbid(unsafe_code)]
#![warn(missing_docs)]

mod computed;
mod effect;
mod host;
mod signal;

use signified_engine::tracking;

pub use computed::Computed;
pub use effect::Effect;
pub use signal::Signal;

use host::Native;

/// Run `f` without tracking: what it reads does not become a dependency of
/// the computed or effect that is running.
pub fn untracked<R>(f: impl FnOnce() -> R) -> R {
    struct Untracked(usize);

    impl Drop for Untracked {
        fn drop(&mut self) {
            // Nested evaluations remove their own frames, even when they
            // panic, so this one is on top.
            drop(tracking::end_frame::<Native>(self.0));
        }
    }

    let _untracked = Untracked(tracking::push_frame::<Native>(None));
    f()
}

/// Whether a read right now would become a dependency (a computed or effect
/// is running, outside [`untracked`]).
pub fn is_tracking() -> bool {
    tracking::is_tracking::<Native>()
}

/// Run `f`, deferring effects until the outermost batch ends, so each runs
/// once for all of `f`'s writes.
///
/// ```
/// use std::cell::Cell;
/// use std::rc::Rc;
/// use signified::{batch, Effect, Signal};
///
/// let (a, b) = (Signal::new(1), Signal::new(2));
/// let runs = Rc::new(Cell::new(0));
/// let _sum = Effect::new({
///     let (a, b, runs) = (a.clone(), b.clone(), runs.clone());
///     move || {
///         let _ = a.get() + b.get();
///         runs.set(runs.get() + 1);
///     }
/// });
/// batch(|| {
///     a.set(10);
///     b.set(20);
/// });
/// assert_eq!(runs.get(), 2);
/// ```
pub fn batch<R>(f: impl FnOnce() -> R) -> R {
    host::batch(f)
}
