//! Watchers: which of a set of values have a new version since the watcher
//! last looked. A watch sits in the watched node's observer list. A
//! notification walk only marks it pending, with no Python code; `changed`
//! later brings the pending values up to date and compares versions, so a
//! value that was invalidated but computed the same result is not reported.

use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

use pyo3::exceptions::PyException;
use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::PyTraverseError;

use crate::engine::node::{Node, Role};
use crate::engine::refresh;

/// One watched value.
struct Watch {
    node: Rc<Node>,
    /// The value's Python object, which refreshing needs.
    handle: Py<PyAny>,
    key: Py<PyAny>,
    /// Previous registration with the same key, or NO_WATCH.
    key_next: u32,
    /// The key's oldest watch: `unwatch` removes a key's watches together, so
    /// it lives as long as this one. Its `reported` dedupes the key.
    group: u32,
    /// The `changed` call that last reported this key (on the group's watch).
    reported: Cell<u64>,
    /// Which registration this is: an index is reused after `unwatch`, so a
    /// pending entry names the registration it was made for.
    generation: u64,
    /// The version last reported (or seen when watching began).
    version: Cell<u64>,
    /// This watch's slot in `node.observers`.
    slot: Cell<u32>,
    pending: Cell<bool>,
}

/// A pending watch: its index and the registration that was invalidated.
type Pending = (u32, u64);

const NO_WATCH: u32 = u32::MAX;

/// The watches of one `Watcher`, by index; removed ones leave `None`.
#[derive(Default)]
pub(crate) struct Watching {
    watches: RefCell<Vec<Option<Watch>>>,
    free: RefCell<Vec<u32>>,
    /// Watches invalidated since the last `changed`, in the order they were.
    pending: RefCell<Vec<Pending>>,
    generations: Cell<u64>,
    calls: Cell<u64>,
    /// Key identity -> all live registrations for it. The watches keep keys
    /// alive, so their addresses cannot be reused while indexed here.
    by_key: RefCell<HashMap<usize, u32>>,
}

impl Watching {
    /// Watch `node` (whose object is `handle`) for `key`. A computed is brought
    /// up to date first, so it is subscribed to what it reads.
    pub(crate) fn watch(
        self: &Rc<Self>,
        py: Python<'_>,
        node: &Rc<Node>,
        handle: &Bound<'_, PyAny>,
        key: Py<PyAny>,
    ) -> PyResult<()> {
        if matches!(node.role, Role::Computed(_)) {
            refresh::ensure_uptodate(py, node, handle)?;
        }
        let index = match self.free.borrow_mut().pop() {
            Some(index) => index,
            None => {
                let mut watches = self.watches.borrow_mut();
                watches.push(None);
                (watches.len() - 1) as u32
            }
        };
        let generation = self.generations.get() + 1;
        self.generations.set(generation);
        let slot = node.observers.push_watch(Rc::downgrade(self), index);
        let key_next = self
            .by_key
            .borrow_mut()
            .insert(key.as_ptr() as usize, index)
            .unwrap_or(NO_WATCH);
        let group = match key_next {
            NO_WATCH => index,
            next => {
                self.watches.borrow()[next as usize]
                    .as_ref()
                    .expect("indexed watch is live")
                    .group
            }
        };
        let watch = Watch {
            group,
            reported: Cell::new(0),
            node: node.clone(),
            handle: handle.clone().unbind(),
            key,
            key_next,
            generation,
            version: Cell::new(node.version.get()),
            slot: Cell::new(slot),
            pending: Cell::new(false),
        };
        let old = self.watches.borrow_mut()[index as usize].replace(watch);
        drop(old);
        Ok(())
    }

    /// Stop every watch registered for `key` (compared by identity).
    pub(crate) fn unwatch(&self, key: &Bound<'_, PyAny>) {
        let Some(mut index) = self.by_key.borrow_mut().remove(&(key.as_ptr() as usize)) else {
            return;
        };
        let mut removed = Vec::new();
        {
            let mut watches = self.watches.borrow_mut();
            while index != NO_WATCH {
                let watch = watches[index as usize]
                    .take()
                    .expect("indexed watch is live");
                let next = watch.key_next;
                removed.push((index, Some(watch)));
                index = next;
            }
        }
        self.free
            .borrow_mut()
            .extend(removed.iter().map(|&(index, _)| index));
        self.forget(
            removed
                .iter()
                .filter_map(|(index, watch)| watch.as_ref().map(|watch| (*index, watch))),
        );
        // Python objects are dropped with nothing borrowed.
        drop(removed);
    }

    /// Take removed watches' entries out of their nodes' observer lists, then
    /// compact those lists. Compacting moves entries, so it waits until every
    /// entry is out: the slots recorded for the removed watches stay right.
    fn forget<'a>(&self, removed: impl Iterator<Item = (u32, &'a Watch)> + Clone) {
        let mut taken = Vec::new();
        for (index, watch) in removed.clone() {
            taken.push(
                watch
                    .node
                    .observers
                    .take_watch(watch.slot.get(), self, index),
            );
        }
        let mut compacted: HashSet<*const Node> = HashSet::new();
        for (_, watch) in removed {
            if compacted.insert(Rc::as_ptr(&watch.node)) {
                watch.node.observers.compact_if_sparse();
            }
        }
        drop(taken);
    }

    /// Mark the watch at `index` pending (during a notification walk).
    pub(crate) fn mark(&self, index: u32) {
        let watches = self.watches.borrow();
        if let Some(Some(watch)) = watches.get(index as usize) {
            if !watch.pending.replace(true) {
                self.pending.borrow_mut().push((index, watch.generation));
            }
        }
    }

    /// Record that the watch at `index` moved to `slot` of its node's observers.
    pub(crate) fn moved(&self, index: u32, slot: u32) {
        if let Some(Some(watch)) = self.watches.borrow().get(index as usize) {
            watch.slot.set(slot);
        }
    }

    /// The node and Python object of the watch that `entry` names, if it is
    /// still registered.
    fn target(
        &self,
        py: Python<'_>,
        (index, generation): Pending,
    ) -> Option<(Rc<Node>, Py<PyAny>)> {
        match self.watches.borrow().get(index as usize) {
            Some(Some(watch)) if watch.generation == generation => {
                Some((watch.node.clone(), watch.handle.clone_ref(py)))
            }
            _ => None,
        }
    }

    /// The keys of pending watches whose value has a new version, each once,
    /// in the order their values were invalidated. A computed whose refresh
    /// raises an `Exception` counts as changed: reading it raises the error.
    /// Any other error (`KeyboardInterrupt`, `SystemExit`) propagates, and
    /// every watch this call took stays pending for the next.
    pub(crate) fn changed(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let pending = std::mem::take(&mut *self.pending.borrow_mut());
        // Bring every pending value up to date first, then compare versions:
        // nothing is reported or recorded until every refresh has finished.
        let mut failed = HashSet::new();
        for &entry in &pending {
            let Some((node, handle)) = self.target(py, entry) else {
                continue;
            };
            if let Some(Some(watch)) = self.watches.borrow().get(entry.0 as usize) {
                watch.pending.set(false);
            }
            if !matches!(node.role, Role::Computed(_)) {
                continue;
            }
            match refresh::ensure_uptodate(py, &node, handle.bind(py)) {
                Ok(()) => {}
                Err(error) if error.is_instance_of::<PyException>(py) => {
                    failed.insert(entry);
                }
                Err(error) => {
                    self.restore(&pending);
                    return Err(error);
                }
            }
        }
        let call = self.calls.get() + 1;
        self.calls.set(call);
        let mut keys = Vec::new();
        let watches = self.watches.borrow();
        for entry in pending {
            // A refresh may have replaced the watch: the new one wasn't invalidated.
            let Some(Some(watch)) = watches.get(entry.0 as usize) else {
                continue;
            };
            if watch.generation != entry.1 {
                continue;
            }
            let version = watch.node.version.get();
            if (failed.contains(&entry) || version != watch.version.get())
                && watches[watch.group as usize]
                    .as_ref()
                    .is_some_and(|group| group.reported.replace(call) != call)
            {
                keys.push(watch.key.clone_ref(py));
            }
            watch.version.set(version);
        }
        Ok(keys)
    }

    /// Put `entries` (taken by an interrupted `changed`) back in front of the
    /// pending watches, still registered ones only, each once.
    fn restore(&self, entries: &[Pending]) {
        let watches = self.watches.borrow();
        let mut pending = self.pending.borrow_mut();
        let mut restored: Vec<Pending> = Vec::with_capacity(entries.len() + pending.len());
        // Each taken entry was queued once. Newly queued entries may overlap
        // after a reentrant refresh; use a set only to filter that second list.
        for &entry in entries {
            if let Some(Some(watch)) = watches.get(entry.0 as usize) {
                if watch.generation == entry.1 {
                    watch.pending.set(true);
                    restored.push(entry);
                }
            }
        }
        if !pending.is_empty() {
            let mut seen: HashSet<Pending> = restored.iter().copied().collect();
            for &entry in pending.iter() {
                if let Some(Some(watch)) = watches.get(entry.0 as usize) {
                    if watch.generation == entry.1 && seen.insert(entry) {
                        restored.push(entry);
                    }
                }
            }
        }
        *pending = restored;
    }

    /// Every unused watch slot appears once on the free list.
    pub(crate) fn len(&self) -> usize {
        self.watches.borrow().len() - self.free.borrow().len()
    }

    pub(crate) fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        if let Ok(watches) = self.watches.try_borrow() {
            for watch in watches.iter().flatten() {
                visit.call(&watch.handle)?;
                visit.call(&watch.key)?;
            }
        }
        Ok(())
    }

    /// Stop every watch.
    pub(crate) fn clear(&self) {
        let watches = std::mem::take(&mut *self.watches.borrow_mut());
        self.by_key.borrow_mut().clear();
        self.forget(
            watches
                .iter()
                .enumerate()
                .filter_map(|(index, watch)| watch.as_ref().map(|watch| (index as u32, watch))),
        );
        self.free.borrow_mut().clear();
        self.pending.borrow_mut().clear();
        drop(watches);
    }
}

impl Drop for Watching {
    fn drop(&mut self) {
        self.clear();
    }
}
