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
//! - Each thread has its own tracking frames, queue and walk depth
//!   (`runtime`); the version clock and plugin hooks are shared. State is only
//!   touched while attached to an interpreter that holds the GIL, which
//!   serializes all access; see the `Send`/`Sync` impls in `node`. The module
//!   declares `gil_used = true`, so a free-threaded interpreter re-enables the
//!   GIL when it is imported.
//! - Every nested refresh holds a level of Python's recursion budget and
//!   checks native stack headroom, so deep graphs raise `RecursionError`.

mod computed;
mod effect;
mod fields;
mod hooks;
mod invalidation;
mod native;
mod node;
mod observer_list;
mod refresh;
mod runtime;
mod scheduler;
mod signal;
mod stack;
mod subscribe;
mod tracking;
mod values;

use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PySuper, PyType};

#[pymodule(gil_used = true)]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<signal::SignalCore>()?;
    m.add_class::<computed::ComputedCore>()?;
    m.add_class::<effect::EffectCore>()?;
    m.add_class::<hooks::Config>()?;
    m.add_class::<tracking::Untracked>()?;
    m.add_class::<scheduler::Batch>()?;
    m.add_class::<signal::SignalAt>()?;
    m.add_class::<fields::FieldSource>()?;
    m.add_class::<fields::TrackedField>()?;
    m.add("config", Bound::new(m.py(), hooks::Config)?)?;
    m.add_function(wrap_pyfunction!(tracking::is_tracking, m)?)?;
    m.add_function(wrap_pyfunction!(values::has_changed, m)?)?;
    m.add_function(wrap_pyfunction!(computed::computed_call, m)?)?;
    m.add_function(wrap_pyfunction!(values::unref, m)?)?;
    m.add_function(wrap_pyfunction!(values::is_reactive, m)?)?;
    native::add_capsule(m)?;
    m.add_function(wrap_pyfunction!(native::_native_test_sum, m)?)?;
    m.add_function(wrap_pyfunction!(native::_native_test_counts, m)?)?;
    Ok(())
}

/// `cls[item]` on the base class itself, and the next `__class_getitem__` in
/// the MRO (`typing.Generic`'s) for the public subclasses.
fn class_getitem(
    base: &Bound<'_, PyType>,
    cls: &Bound<'_, PyType>,
    item: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let py = cls.py();
    if cls.is(base) {
        let alias = py
            .import(intern!(py, "types"))?
            .getattr(intern!(py, "GenericAlias"))?
            .call1((cls, item))?;
        return Ok(alias.unbind());
    }
    let next = PySuper::new(base, cls)?.getattr(intern!(py, "__class_getitem__"))?;
    Ok(next.call1((item,))?.unbind())
}
