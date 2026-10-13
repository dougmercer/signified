//! A node's observer list: the computeds and effects that read it, and the
//! objects passed to its `_subscribe()`, in the order they subscribed.
//!
//! A removed entry leaves a vacant slot, so positions stay put during a
//! notification walk. The list compacts once it gets sparse, and the slots
//! recorded elsewhere follow the entries that move.

use std::cell::{Ref, RefCell};
use std::collections::HashMap;
use std::rc::Weak;

use pyo3::prelude::*;
use pyo3::types::PyWeakrefReference;

use crate::engine::node::Node;
use crate::engine::runtime::with_rt;

/// Observer lists at least this long compact once half their slots are vacant.
const COMPACT_MIN_LEN: usize = 16;

/// An entry in a node's observer list.
pub(crate) enum Observer {
    /// A removed entry, dropped when the list compacts.
    Vacant,
    /// A computed or effect; `link` is the position of its link to this node.
    Consumer { node: Weak<Node>, link: u32 },
    /// An object passed to `_subscribe()`, held weakly. `id` is its address,
    /// compared before the weak reference is resolved.
    Python {
        reference: Py<PyWeakrefReference>,
        id: usize,
    },
}

#[derive(Default)]
pub(crate) struct ObserverList(RefCell<Slots>);

#[derive(Default)]
struct Slots {
    entries: Vec<Observer>,
    vacant: u32,
    /// The slot of each `_subscribe()` observer, by the observer's address;
    /// created on first use. Boxed so nodes without such observers stay small.
    #[allow(clippy::box_collection)]
    subscribers: Option<Box<HashMap<usize, u32>>>,
}

impl ObserverList {
    /// Whether every slot is vacant.
    pub(crate) fn is_empty(&self) -> bool {
        let slots = self.0.borrow();
        slots.entries.len() <= slots.vacant as usize
    }

    /// Slots in the list, vacant ones included.
    pub(crate) fn slot_count(&self) -> usize {
        self.0.borrow().entries.len()
    }

    /// The entry in `slot`. It borrows the list, so no Python code may run
    /// while it is held.
    pub(crate) fn get(&self, slot: usize) -> Option<Ref<'_, Observer>> {
        Ref::filter_map(self.0.borrow(), |slots| slots.entries.get(slot)).ok()
    }

    /// Add a computed or effect whose link to this node is at `link`, and
    /// return its slot.
    pub(crate) fn push_consumer(&self, node: Weak<Node>, link: u32) -> u32 {
        let mut slots = self.0.borrow_mut();
        slots.entries.push(Observer::Consumer { node, link });
        (slots.entries.len() - 1) as u32
    }

    /// Add the `_subscribe()` observer at address `id`, held by `reference`.
    pub(crate) fn push_subscriber(&self, reference: Py<PyWeakrefReference>, id: usize) {
        let mut slots = self.0.borrow_mut();
        slots.entries.push(Observer::Python { reference, id });
        let slot = (slots.entries.len() - 1) as u32;
        slots
            .subscribers
            .get_or_insert_with(Default::default)
            .insert(id, slot);
    }

    /// The slot recorded for the `_subscribe()` observer at address `id`.
    pub(crate) fn subscriber_slot(&self, id: usize) -> Option<u32> {
        self.0.borrow().subscribers.as_ref()?.get(&id).copied()
    }

    /// Record that the consumer in `slot` moved its link to this node to
    /// `position`.
    pub(crate) fn set_link(&self, slot: u32, position: u32) {
        if let Some(Observer::Consumer { link, .. }) =
            self.0.borrow_mut().entries.get_mut(slot as usize)
        {
            *link = position;
        }
    }

    /// Remove the consumer `key`'s entry, if `slot` still holds it.
    pub(crate) fn remove_consumer(&self, slot: u32, key: usize) {
        let owned = matches!(
            self.0.borrow().entries.get(slot as usize),
            Some(Observer::Consumer { node, .. }) if node.as_ptr() as usize == key
        );
        if owned {
            drop(self.vacate(slot));
        }
    }

    /// Remove the observer in `slot` without compacting, and return it so the
    /// caller drops it with nothing borrowed.
    pub(crate) fn take(&self, slot: u32) -> Observer {
        let mut slots = self.0.borrow_mut();
        let removed = match slots.entries.get_mut(slot as usize) {
            Some(entry) => std::mem::replace(entry, Observer::Vacant),
            None => Observer::Vacant,
        };
        match &removed {
            Observer::Vacant => return removed,
            Observer::Python { id, .. } => {
                if let Some(subscribers) = slots.subscribers.as_mut() {
                    if subscribers.get(id) == Some(&slot) {
                        subscribers.remove(id);
                    }
                }
            }
            Observer::Consumer { .. } => {}
        }
        slots.vacant += 1;
        removed
    }

    /// Remove the observer in `slot`, compacting the list if it got sparse.
    pub(crate) fn vacate(&self, slot: u32) -> Observer {
        let removed = self.take(slot);
        self.compact_if_sparse();
        removed
    }

    /// Drop vacant slots once they make up half of a long list. Consumers and
    /// `_subscribe()` observers whose entries move get their slots updated. Not
    /// during a notification walk, which iterates the list by position.
    pub(crate) fn compact_if_sparse(&self) {
        let mut slots = self.0.borrow_mut();
        let Slots {
            entries,
            vacant,
            subscribers,
        } = &mut *slots;
        let len = entries.len();
        let all_vacant = *vacant as usize == len;
        let sparse = len >= COMPACT_MIN_LEN && *vacant as usize * 2 > len;
        if !(all_vacant || sparse) || with_rt(|rt| rt.wave_depth.get() > 0) {
            return;
        }
        let mut write = 0;
        for read in 0..entries.len() {
            if matches!(entries[read], Observer::Vacant) {
                continue;
            }
            if read != write {
                entries.swap(read, write);
                match &entries[write] {
                    Observer::Consumer {
                        node: consumer,
                        link,
                    } => {
                        if let Some(consumer) = consumer.upgrade() {
                            if let Some(link) =
                                consumer.reader_state().deps.borrow().get(*link as usize)
                            {
                                link.slot.set(write as u32);
                            }
                        }
                    }
                    Observer::Python { id, .. } => {
                        if let Some(slot) = subscribers.as_mut().and_then(|map| map.get_mut(id)) {
                            if *slot == read as u32 {
                                *slot = write as u32;
                            }
                        }
                    }
                    Observer::Vacant => {}
                }
            }
            write += 1;
        }
        // Only vacant entries are truncated, so nothing Python is dropped here.
        entries.truncate(write);
        *vacant = 0;
    }
}
