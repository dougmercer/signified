//! The engine's record of one reactive value: a `Node`, with its version and
//! observer list, a `Role` holding what only its kind needs, and the host's
//! payload.

use std::cell::{Cell, Ref, RefCell};
use std::num::NonZeroU64;
use std::rc::Rc;

use crate::observers::ObserverList;
use crate::Host;
use crate::{runtime, tracking};

/// Staleness of a computed node, ordered by invalidation priority.
/// `Uninitialized` sits above `MustRefresh` so invalidation never downgrades a
/// node that has not computed yet.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum State {
    Fresh,
    Stale,
    MustRefresh,
    Uninitialized,
}

pub(crate) const NEVER: u64 = u64::MAX;
pub(crate) const NO_SLOT: u32 = u32::MAX;

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
pub struct DepLink<H: Host> {
    pub node: Rc<Node<H>>,
    /// Whatever the host keeps with the edge (the Python host keeps the
    /// dependency's object, which keeps it alive and visible to the GC).
    pub handle: H::Handle,
    pub(crate) version: u64,
    pub(crate) read_version: u64,
    pub(crate) seen: u64,
    /// This consumer's entry in `node.observers`, once subscribed.
    pub(crate) slot: Cell<u32>,
    /// `node.reader_link` before this run, restored when the run ends.
    pub(crate) rollback: Cell<ReaderLink>,
}

/// One reactive value. `P` is the host's payload; a host whose payload is a
/// trait object makes each node with its concrete payload type and coerces
/// `Rc<Node<H, Concrete>>` to `Rc<Node<H>>`.
pub struct Node<H: Host, P: ?Sized = <H as Host>::Payload> {
    pub version: Cell<u64>,
    pub observers: ObserverList<H>,
    /// Set while a consumer that reads this node runs; see
    /// `tracking::register_dependency`.
    pub(crate) reader_link: Cell<ReaderLink>,
    pub role: Role<H>,
    pub payload: P,
}

/// What kind of node this is, with the state only that kind keeps.
pub enum Role<H: Host> {
    Signal,
    Computed(Box<ComputedState<H>>),
    Effect(Box<EffectState<H>>),
}

impl<H: Host> Role<H> {
    /// A computed that has not evaluated yet.
    pub fn computed(data: H::ComputedData) -> Role<H> {
        Role::Computed(Box::new(ComputedState {
            reader: ReaderState::default(),
            state: Cell::new(State::Uninitialized),
            computing: Cell::new(false),
            notified: Cell::new(false),
            clock_seen: Cell::new(NEVER),
            data,
        }))
    }

    /// An effect that is not active yet.
    pub fn effect(data: H::EffectData) -> Role<H> {
        Role::Effect(Box::new(EffectState {
            reader: ReaderState::default(),
            active: Cell::new(false),
            has_run: Cell::new(false),
            queued: Cell::new(None),
            runs: Cell::new(0),
            run_epoch: Cell::new(0),
            data,
        }))
    }

    /// What a computed or effect read; `None` for a signal.
    pub fn reader_state(&self) -> Option<&ReaderState<H>> {
        match self {
            Role::Signal => None,
            Role::Computed(computed) => Some(&computed.reader),
            Role::Effect(effect) => Some(&effect.reader),
        }
    }
}

/// What a consumer (a computed or effect) read on its last run.
pub struct ReaderState<H: Host> {
    pub(crate) token: Cell<u64>,
    pub(crate) deps: RefCell<Vec<DepLink<H>>>,
}

impl<H: Host> Default for ReaderState<H> {
    fn default() -> Self {
        ReaderState {
            token: Cell::new(0),
            deps: RefCell::new(Vec::new()),
        }
    }
}

impl<H: Host> ReaderState<H> {
    /// The dependencies the last run read, in the order they were first read.
    /// No host code may run while this is held.
    pub fn deps(&self) -> Ref<'_, [DepLink<H>]> {
        Ref::map(self.deps.borrow(), Vec::as_slice)
    }

    /// Like `deps`, or `None` while the list is being changed (for a garbage
    /// collector's traversal, which may run at any allocation).
    pub fn try_deps(&self) -> Option<Ref<'_, [DepLink<H>]>> {
        self.deps
            .try_borrow()
            .ok()
            .map(|deps| Ref::map(deps, Vec::as_slice))
    }
}

pub struct ComputedState<H: Host> {
    pub reader: ReaderState<H>,
    pub state: Cell<State>,
    /// Set while evaluating, to detect cycles.
    pub computing: Cell<bool>,
    /// Observers were told about the last change and not told since a read.
    pub notified: Cell<bool>,
    /// The clock when this node was last known current.
    pub clock_seen: Cell<u64>,
    pub data: H::ComputedData,
}

pub struct EffectState<H: Host> {
    pub reader: ReaderState<H>,
    /// Not disposed.
    pub active: Cell<bool>,
    /// Has run at least once.
    pub has_run: Cell<bool>,
    /// The queue sequence number while queued.
    pub queued: Cell<Option<NonZeroU64>>,
    /// Runs in the flush numbered `run_epoch`.
    pub(crate) runs: Cell<u32>,
    pub(crate) run_epoch: Cell<u64>,
    pub data: H::EffectData,
}

impl<H: Host, P> Node<H, P> {
    pub fn new(role: Role<H>, payload: P) -> Node<H, P> {
        Node {
            version: Cell::new(0),
            observers: ObserverList::default(),
            reader_link: Cell::new(NO_READER),
            role,
            payload,
        }
    }
}

impl<H: Host, P: ?Sized> Node<H, P> {
    /// What this computed or effect read.
    pub fn reader_state(&self) -> &ReaderState<H> {
        self.role
            .reader_state()
            .expect("only computeds and effects read other nodes")
    }

    pub fn computed_state(&self) -> &ComputedState<H> {
        match &self.role {
            Role::Computed(computed) => computed,
            _ => panic!("expected a computed node"),
        }
    }

    pub fn effect_state(&self) -> &EffectState<H> {
        match &self.role {
            Role::Effect(effect) => effect,
            _ => panic!("expected an effect node"),
        }
    }

    /// Identifies this node among live nodes: its address.
    pub(crate) fn key(&self) -> usize {
        self as *const Self as *const () as usize
    }
}

impl<H: Host, P: ?Sized> Drop for Node<H, P> {
    /// A freed consumer unsubscribes from its dependencies right away.
    fn drop(&mut self) {
        let key = self.key();
        let reader = match &mut self.role {
            Role::Signal => return,
            Role::Computed(computed) => &mut computed.reader,
            Role::Effect(effect) => &mut effect.reader,
        };
        let links = std::mem::take(reader.deps.get_mut());
        tracking::unlink(key, &links);
        // Dropping the links can free dependencies and run host code;
        // nothing is borrowed here.
        if H::DEFER_DROPS {
            for DepLink { node, handle, .. } in links {
                runtime::release(node);
                drop(handle);
            }
        } else {
            drop(links);
        }
    }
}
