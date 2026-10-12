//! What a node holds for Python: its value, equality and name (`PySlot`),
//! a computed's function, cached error and restore point (`PyComputed`), and
//! an effect's callback (`PyEffect`). The graph bookkeeping around them is
//! the engine's `Node`.

use std::cell::RefCell;
use std::rc::{Rc, Weak};

use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::types::PyString;
use pyo3::PyTraverseError;
use signified_engine::{tracking, Role};

use crate::host::PyHost;
use crate::native::NativeKernel;

/// A node of the Python host.
pub(crate) type Node = signified_engine::Node<PyHost>;

/// `Rc<Node>` made `Send` and `Sync` so a Python object can own one.
///
/// SAFETY: nodes are only touched while attached to an interpreter that holds
/// the GIL, which lets one thread run at a time (the module is
/// `gil_used = true`), so the non-atomic reference counts and the cells are
/// never accessed concurrently. No borrow is held across a call into Python,
/// so a thread switch inside such a call never observes a cell mid-update.
/// Each thread tracks and schedules on its own; using one graph from several
/// threads at the same time is unsupported, but it cannot cause a data race.
/// Thread-exit cleanup runs without the GIL, so work a thread leaves queued is
/// leaked rather than dropped; see the engine's `Queue`.
pub(crate) struct Shared(pub(crate) Rc<Node>);

unsafe impl Send for Shared {}
unsafe impl Sync for Shared {}

impl Shared {
    pub(crate) fn new(role: Role<PyHost>) -> Shared {
        Shared(Rc::new(Node::new(role, PySlot::default())))
    }
}

impl std::ops::Deref for Shared {
    type Target = Rc<Node>;

    fn deref(&self) -> &Rc<Node> {
        &self.0
    }
}

/// `Weak<Node>` made `Send` and `Sync`, for the same reason as `Shared`.
pub(crate) struct WeakShared(pub(crate) Weak<Node>);

unsafe impl Send for WeakShared {}
unsafe impl Sync for WeakShared {}

/// Every node's Python data.
#[derive(Default)]
pub(crate) struct PySlot {
    pub(crate) value: RefCell<Option<Py<PyAny>>>,
    pub(crate) equal: RefCell<Option<Py<PyAny>>>,
    pub(crate) name: RefCell<Option<Py<PyAny>>>,
}

/// A computed's Python data.
#[derive(Default)]
pub(crate) struct PyComputed {
    pub(crate) compute: RefCell<Option<Compute>>,
    pub(crate) error: RefCell<Option<CachedError>>,
    pub(crate) restore: RefCell<Option<RestorePoint>>,
}

/// An effect's Python data.
#[derive(Default)]
pub(crate) struct PyEffect {
    /// The zero-argument callback.
    pub(crate) function: RefCell<Option<Py<PyAny>>>,
}

/// How a computed produces its value.
pub(crate) enum Compute {
    /// A zero-argument Python callable.
    Function(Py<PyAny>),
    /// `func(*resolved args)`, with reactive arguments resolved in Rust.
    Call {
        func: Py<PyAny>,
        args: Vec<Py<PyAny>>,
    },
    /// A `Binding`: read the holder signal, then the source it holds.
    Source(Py<PyAny>),
    /// A kernel from another extension (see `native`) over resolved arguments.
    Native {
        kernel: Rc<NativeKernel>,
        args: Vec<Py<PyAny>>,
    },
}

impl Compute {
    pub(crate) fn clone_ref(&self, py: Python<'_>) -> Compute {
        match self {
            Compute::Function(f) => Compute::Function(f.clone_ref(py)),
            Compute::Call { func, args } => Compute::Call {
                func: func.clone_ref(py),
                args: args.iter().map(|arg| arg.clone_ref(py)).collect(),
            },
            Compute::Source(holder) => Compute::Source(holder.clone_ref(py)),
            Compute::Native { kernel, args } => Compute::Native {
                kernel: Rc::clone(kernel),
                args: args.iter().map(|arg| arg.clone_ref(py)).collect(),
            },
        }
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        match self {
            Compute::Function(f) => visit.call(f),
            Compute::Call { func, args } => {
                visit.call(func)?;
                for arg in args {
                    visit.call(arg)?;
                }
                Ok(())
            }
            Compute::Source(holder) => visit.call(holder),
            Compute::Native { args, .. } => {
                for arg in args {
                    visit.call(arg)?;
                }
                Ok(())
            }
        }
    }
}

/// A failed evaluation, kept as Python objects so the GC can traverse it.
pub(crate) struct CachedError {
    pub(crate) exception: Py<PyAny>,
    pub(crate) traceback: Option<Py<PyAny>>,
}

/// What a `Binding` returns to after `at()`, if its source is unchanged.
pub(crate) struct RestorePoint {
    pub(crate) value: Py<PyAny>,
    pub(crate) version: u64,
    pub(crate) holder: Rc<Node>,
    pub(crate) source: Py<PyAny>,
    pub(crate) source_node: Rc<Node>,
    pub(crate) source_version: u64,
}

/// The Python side of a node.
pub(crate) trait NodeExt {
    /// The stored value, without tracking a read.
    fn raw_value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny>;
    fn name_or_empty<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny>;
    fn set_name(&self, name: Py<PyAny>);
    fn equal_or_none(&self, py: Python<'_>) -> Py<PyAny>;
    fn set_equal(&self, py: Python<'_>, equal: Py<PyAny>);
    fn computed_data(&self) -> &PyComputed;
    fn effect_data(&self) -> &PyEffect;
    /// Visit every Python object this node owns; busy cells are skipped.
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError>;
    /// Drop every Python object this node owns (for `__clear__`).
    fn clear(self: &Rc<Self>);
}

impl NodeExt for Node {
    fn raw_value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self.payload.value.borrow().as_ref() {
            Some(value) => value.bind(py).clone(),
            None => py.None().into_bound(py),
        }
    }

    fn name_or_empty<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self.payload.name.borrow().as_ref() {
            Some(name) => name.bind(py).clone(),
            None => PyString::new(py, "").into_any(),
        }
    }

    fn set_name(&self, name: Py<PyAny>) {
        let old = self.payload.name.replace(Some(name));
        drop(old);
    }

    fn equal_or_none(&self, py: Python<'_>) -> Py<PyAny> {
        match self.payload.equal.borrow().as_ref() {
            Some(equal) => equal.clone_ref(py),
            None => py.None(),
        }
    }

    fn set_equal(&self, py: Python<'_>, equal: Py<PyAny>) {
        let equal = if equal.is_none(py) { None } else { Some(equal) };
        let old = self.payload.equal.replace(equal);
        drop(old);
    }

    fn computed_data(&self) -> &PyComputed {
        &self.computed_state().data
    }

    fn effect_data(&self) -> &PyEffect {
        &self.effect_state().data
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        let slot = &self.payload;
        for cell in [&slot.value, &slot.equal, &slot.name] {
            if let Ok(object) = cell.try_borrow() {
                if let Some(object) = object.as_ref() {
                    visit.call(object)?;
                }
            }
        }
        match &self.role {
            Role::Signal => {}
            Role::Computed(computed) => {
                let data = &computed.data;
                if let Ok(compute) = data.compute.try_borrow() {
                    if let Some(compute) = compute.as_ref() {
                        compute.traverse(visit)?;
                    }
                }
                if let Ok(error) = data.error.try_borrow() {
                    if let Some(cached) = error.as_ref() {
                        visit.call(&cached.exception)?;
                        if let Some(traceback) = cached.traceback.as_ref() {
                            visit.call(traceback)?;
                        }
                    }
                }
                if let Ok(restore) = data.restore.try_borrow() {
                    if let Some(point) = restore.as_ref() {
                        visit.call(&point.value)?;
                        visit.call(&point.source)?;
                    }
                }
            }
            Role::Effect(effect) => {
                if let Ok(function) = effect.data.function.try_borrow() {
                    if let Some(function) = function.as_ref() {
                        visit.call(function)?;
                    }
                }
            }
        }
        if let Some(reader) = self.role.reader_state() {
            if let Some(deps) = reader.try_deps() {
                for link in deps.iter() {
                    visit.call(&link.handle)?;
                }
            }
        }
        Ok(())
    }

    fn clear(self: &Rc<Self>) {
        tracking::detach_all_deps(self);
        let slot = &self.payload;
        let value = slot.value.take();
        let equal = slot.equal.take();
        let name = slot.name.take();
        let computed = match &self.role {
            Role::Computed(computed) => Some((
                computed.data.compute.take(),
                computed.data.error.take(),
                computed.data.restore.take(),
            )),
            _ => None,
        };
        let function = match &self.role {
            Role::Effect(effect) => effect.data.function.take(),
            _ => None,
        };
        drop((value, equal, name, computed, function));
    }
}
