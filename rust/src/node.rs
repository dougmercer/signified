//! The engine's record of one reactive value: a `Node`, with its value,
//! version and observer list, and a `Role` holding what only its kind needs.

use std::cell::{Cell, RefCell};
use std::num::NonZeroU64;
use std::rc::{Rc, Weak};

use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::types::PyString;
use pyo3::PyTraverseError;

use crate::observer_list::ObserverList;
use crate::tracking;

/// Staleness of a computed node, ordered by invalidation priority.
/// `Uninitialized` sits above `MustRefresh` so invalidation never downgrades a
/// node that has not computed yet.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub(crate) enum State {
    Fresh,
    Stale,
    MustRefresh,
    Uninitialized,
}

pub(crate) const NEVER: u64 = u64::MAX;
pub(crate) const NO_SLOT: u32 = u32::MAX;

/// `Rc<Node>` made `Send` and `Sync` so a Python object can own one.
///
/// SAFETY: nodes are only touched while attached to an interpreter that holds
/// the GIL, which lets one thread run at a time (the module is
/// `gil_used = true`), so the non-atomic reference counts and the cells are
/// never accessed concurrently. No borrow is held across a call into Python,
/// so a thread switch inside such a call never observes a cell mid-update.
/// Concurrent use from several threads is unsupported, but it cannot cause a
/// data race.
pub(crate) struct Shared(pub(crate) Rc<Node>);

unsafe impl Send for Shared {}
unsafe impl Sync for Shared {}

impl Shared {
    pub(crate) fn new(role: Role) -> Shared {
        Shared(Rc::new(Node::new(role)))
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
        }
    }
}

/// Which consumer last read a node during a run, and where that consumer's
/// link to the node is.
#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) struct ReaderLink {
    pub(crate) reader: usize,
    pub(crate) position: u32,
}

const NO_READER: ReaderLink = ReaderLink {
    reader: 0,
    position: 0,
};

/// Edge from a consumer to one dependency, reused across runs.
pub(crate) struct DepLink {
    pub(crate) node: Rc<Node>,
    /// The dependency's Python object; keeps it alive and is visible to the GC.
    pub(crate) handle: Py<PyAny>,
    pub(crate) version: u64,
    pub(crate) read_version: u64,
    pub(crate) seen: u64,
    /// This consumer's entry in `node.observers`, once subscribed.
    pub(crate) slot: Cell<u32>,
    /// `node.reader_link` before this run, restored when the run ends.
    pub(crate) rollback: Cell<ReaderLink>,
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

pub(crate) struct Node {
    pub(crate) version: Cell<u64>,
    pub(crate) value: RefCell<Option<Py<PyAny>>>,
    pub(crate) equal: RefCell<Option<Py<PyAny>>>,
    pub(crate) name: RefCell<Option<Py<PyAny>>>,
    pub(crate) observers: ObserverList,
    /// Set while a consumer that reads this node runs; see `register_dependency`.
    pub(crate) reader_link: Cell<ReaderLink>,
    pub(crate) role: Role,
}

/// What kind of node this is, with the state only that kind keeps.
pub(crate) enum Role {
    Signal,
    Computed(Box<ComputedState>),
    Effect(Box<EffectState>),
}

impl Role {
    /// What a computed or effect read; `None` for a signal.
    pub(crate) fn reader_state(&self) -> Option<&ReaderState> {
        match self {
            Role::Signal => None,
            Role::Computed(computed) => Some(&computed.reader),
            Role::Effect(effect) => Some(&effect.reader),
        }
    }
}

/// What a consumer (a computed or effect) read on its last run.
#[derive(Default)]
pub(crate) struct ReaderState {
    pub(crate) token: Cell<u64>,
    pub(crate) deps: RefCell<Vec<DepLink>>,
}

pub(crate) struct ComputedState {
    pub(crate) reader: ReaderState,
    pub(crate) compute: RefCell<Option<Compute>>,
    pub(crate) state: Cell<State>,
    pub(crate) computing: Cell<bool>,
    pub(crate) notified: Cell<bool>,
    pub(crate) clock_seen: Cell<u64>,
    pub(crate) error: RefCell<Option<CachedError>>,
    pub(crate) restore: RefCell<Option<RestorePoint>>,
}

/// A computed starts uninitialized.
impl Default for ComputedState {
    fn default() -> ComputedState {
        ComputedState {
            reader: ReaderState::default(),
            compute: RefCell::new(None),
            state: Cell::new(State::Uninitialized),
            computing: Cell::new(false),
            notified: Cell::new(false),
            clock_seen: Cell::new(NEVER),
            error: RefCell::new(None),
            restore: RefCell::new(None),
        }
    }
}

#[derive(Default)]
pub(crate) struct EffectState {
    pub(crate) reader: ReaderState,
    /// The zero-argument callback.
    pub(crate) function: RefCell<Option<Py<PyAny>>>,
    /// Not disposed.
    pub(crate) active: Cell<bool>,
    /// Has run at least once.
    pub(crate) has_run: Cell<bool>,
    /// The queue sequence number while queued.
    pub(crate) queued: Cell<Option<NonZeroU64>>,
    /// Runs in the flush numbered `run_epoch`.
    pub(crate) runs: Cell<u32>,
    pub(crate) run_epoch: Cell<u64>,
}

impl Node {
    pub(crate) fn new(role: Role) -> Node {
        Node {
            version: Cell::new(0),
            value: RefCell::new(None),
            equal: RefCell::new(None),
            name: RefCell::new(None),
            observers: ObserverList::default(),
            reader_link: Cell::new(NO_READER),
            role,
        }
    }

    /// What this computed or effect read.
    pub(crate) fn reader_state(&self) -> &ReaderState {
        self.role
            .reader_state()
            .expect("only computeds and effects read other nodes")
    }

    pub(crate) fn computed_state(&self) -> &ComputedState {
        match &self.role {
            Role::Computed(computed) => computed,
            _ => panic!("expected a computed node"),
        }
    }

    pub(crate) fn effect_state(&self) -> &EffectState {
        match &self.role {
            Role::Effect(effect) => effect,
            _ => panic!("expected an effect node"),
        }
    }

    /// The stored value, without tracking a read.
    pub(crate) fn raw_value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self.value.borrow().as_ref() {
            Some(value) => value.bind(py).clone(),
            None => py.None().into_bound(py),
        }
    }

    pub(crate) fn name_or_empty<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self.name.borrow().as_ref() {
            Some(name) => name.bind(py).clone(),
            None => PyString::new(py, "").into_any(),
        }
    }

    pub(crate) fn set_name(&self, name: Py<PyAny>) {
        let old = self.name.replace(Some(name));
        drop(old);
    }

    pub(crate) fn equal_or_none(&self, py: Python<'_>) -> Py<PyAny> {
        match self.equal.borrow().as_ref() {
            Some(equal) => equal.clone_ref(py),
            None => py.None(),
        }
    }

    pub(crate) fn set_equal(&self, py: Python<'_>, equal: Py<PyAny>) {
        let equal = if equal.is_none(py) { None } else { Some(equal) };
        let old = self.equal.replace(equal);
        drop(old);
    }

    /// Visit every Python object this node owns; busy cells are skipped.
    pub(crate) fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        for cell in [&self.value, &self.equal, &self.name] {
            if let Ok(object) = cell.try_borrow() {
                if let Some(object) = object.as_ref() {
                    visit.call(object)?;
                }
            }
        }
        match &self.role {
            Role::Signal => {}
            Role::Computed(computed) => {
                if let Ok(compute) = computed.compute.try_borrow() {
                    if let Some(compute) = compute.as_ref() {
                        compute.traverse(visit)?;
                    }
                }
                if let Ok(error) = computed.error.try_borrow() {
                    if let Some(cached) = error.as_ref() {
                        visit.call(&cached.exception)?;
                        if let Some(traceback) = cached.traceback.as_ref() {
                            visit.call(traceback)?;
                        }
                    }
                }
                if let Ok(restore) = computed.restore.try_borrow() {
                    if let Some(point) = restore.as_ref() {
                        visit.call(&point.value)?;
                        visit.call(&point.source)?;
                    }
                }
            }
            Role::Effect(effect) => {
                if let Ok(function) = effect.function.try_borrow() {
                    if let Some(function) = function.as_ref() {
                        visit.call(function)?;
                    }
                }
            }
        }
        if let Some(reader) = self.role.reader_state() {
            if let Ok(deps) = reader.deps.try_borrow() {
                for link in deps.iter() {
                    visit.call(&link.handle)?;
                }
            }
        }
        Ok(())
    }

    /// Drop every Python object this node owns (for `__clear__`).
    pub(crate) fn clear(self: &Rc<Self>) {
        tracking::detach_all_deps(self);
        let value = self.value.take();
        let equal = self.equal.take();
        let name = self.name.take();
        let computed = match &self.role {
            Role::Computed(computed) => Some((
                computed.compute.take(),
                computed.error.take(),
                computed.restore.take(),
            )),
            _ => None,
        };
        let function = match &self.role {
            Role::Effect(effect) => effect.function.take(),
            _ => None,
        };
        drop((value, equal, name, computed, function));
    }
}

impl Drop for Node {
    /// A freed consumer unsubscribes from its dependencies right away.
    fn drop(&mut self) {
        let key = self as *const Node as usize;
        let reader = match &mut self.role {
            Role::Signal => return,
            Role::Computed(computed) => &mut computed.reader,
            Role::Effect(effect) => &mut effect.reader,
        };
        let links = std::mem::take(reader.deps.get_mut());
        tracking::unlink(key, &links);
        // Dropping the links can free dependencies and run Python code;
        // nothing is borrowed here.
        drop(links);
    }
}
