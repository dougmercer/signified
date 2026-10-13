//! The reactive graph: push invalidation, pull refresh with version checks,
//! mark-and-sweep dependency tracking, and the queue that runs effects.
//!
//! The engine contains no `unsafe` code; the compiler enforces it below. It
//! uses only pyo3's safe API, and the modules outside it hold what cannot be
//! safe: making nodes `Send` and `Sync` for Python objects (`shared`), the
//! recursion guard (`stack`), and the Python classes, whose generated code
//! uses `unsafe`.
//!
//! Rules that keep the graph consistent while Python code runs inside it:
//! - Never call Python, allocate a Python object, or drop a `Py` while a
//!   `RefCell` in a `Node` or the runtime is borrowed. Copy what you need out,
//!   release the borrow, then call, allocate or drop. Allocating can run the
//!   garbage collector, and dropping can run `__del__` and weakref callbacks.
//! - `__traverse__` only uses `try_borrow`; a busy cell is skipped.
//! - Each thread has its own tracking frames, queue and walk depth
//!   (`runtime`); the version clock and plugin hooks are shared.

#![forbid(unsafe_code)]

pub(crate) mod effect;
pub(crate) mod invalidation;
pub(crate) mod node;
pub(crate) mod observer_list;
pub(crate) mod refresh;
pub(crate) mod runtime;
pub(crate) mod scheduler;
pub(crate) mod tracking;
