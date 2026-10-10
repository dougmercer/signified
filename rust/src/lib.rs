//! `signified._core`: the reactive graph engine behind `signified.Signal`,
//! `Computed`, `Binding` and `Effect`.
//!
//! Push invalidation, pull refresh with version checks, and mark-and-sweep
//! dependency tracking. Python sees base classes; the public classes in
//! `signified/_reactive.py` subclass them together with the operator mixin.
//!
//! Rules that keep this sound while Python code runs inside the engine:
//! - Never call Python, allocate a Python object, or drop a `Py` while a
//!   `RefCell` in a `Node` or the runtime is borrowed. Copy what you need out,
//!   release the borrow, then call, allocate or drop. Allocating can run the
//!   garbage collector, and dropping can run `__del__` and weakref callbacks.
//! - `__traverse__` only uses `try_borrow`; a busy cell is skipped.
//! - State is only touched while attached to an interpreter that holds the GIL,
//!   which serializes all access; see the `Send`/`Sync` impls in `graph`. The
//!   module declares `gil_used = true`, so a free-threaded interpreter
//!   re-enables the GIL when it is imported.
//! - Every nested refresh holds a level of Python's recursion budget and
//!   checks native stack headroom, so deep graphs raise `RecursionError`.

mod classes;
mod config;
mod effects;
mod graph;

use pyo3::prelude::*;

#[pymodule(gil_used = true)]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<classes::SignalCore>()?;
    m.add_class::<classes::ComputedCore>()?;
    m.add_class::<classes::EffectCore>()?;
    m.add_class::<config::Config>()?;
    m.add_class::<classes::Untracked>()?;
    m.add_class::<classes::Batch>()?;
    m.add_class::<classes::SignalAt>()?;
    m.add("config", Bound::new(m.py(), config::Config)?)?;
    m.add_function(wrap_pyfunction!(classes::push_untracked, m)?)?;
    m.add_function(wrap_pyfunction!(classes::pop_untracked, m)?)?;
    m.add_function(wrap_pyfunction!(classes::is_tracking, m)?)?;
    m.add_function(wrap_pyfunction!(classes::has_changed, m)?)?;
    m.add_function(wrap_pyfunction!(classes::computed_call, m)?)?;
    m.add_function(wrap_pyfunction!(classes::begin_batch, m)?)?;
    m.add_function(wrap_pyfunction!(classes::end_batch, m)?)?;
    m.add_function(wrap_pyfunction!(classes::flush, m)?)?;
    m.add_function(wrap_pyfunction!(classes::_register_standard_types, m)?)?;
    m.add_function(wrap_pyfunction!(classes::unref, m)?)?;
    m.add_function(wrap_pyfunction!(classes::is_reactive, m)?)?;
    Ok(())
}
