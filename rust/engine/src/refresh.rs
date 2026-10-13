//! Pull: bring a computed up to date when it is read. A stale computed first
//! brings its computed dependencies up to date and compares versions, and is
//! evaluated again (by [`Host::refresh`]) only if one of them changed.
//!
//! A host's `refresh` uses these steps, in order:
//! 1. [`check_cycle`];
//! 2. [`tracking::start_refresh`], [`tracking::push_frame`] with the node,
//!    evaluate, [`tracking::end_frame`], then [`tracking::commit_refresh`]
//!    (after a failed evaluation too), with `computing` set around them;
//! 3. store the outcome, and [`settle`] with whether it changed.

use std::rc::Rc;

use crate::node::{Node, Role, State};
use crate::runtime::bump_version;
use crate::tracking::{self, is_evaluating};
use crate::{EngineError, Host};

/// Bring a computed up to date: nothing if it is fresh, a version check if
/// it is stale, and [`Host::refresh`] if a dependency changed.
///
/// Always inlined, so it adds no stack frame to the recursion through it: a
/// read refreshes in the reader's frame, and [`dependencies_changed`] checks
/// a chain one frame per level. See [`Host::refresh`] for why that matters.
#[inline(always)]
pub fn ensure_uptodate<H: Host>(
    cx: H::Cx<'_>,
    node: &Rc<Node<H>>,
    handle: &H::Handle,
) -> Result<(), H::Error> {
    let computed = node.computed_state();
    if computed.state.get() == State::Fresh {
        return Ok(());
    }
    H::nested(cx, || {
        // Any refresh attempt means observers must be told about the next change.
        computed.notified.set(false);
        let state = computed.state.get();
        // The graph has not changed since this node was last current.
        if state == State::Stale && computed.clock_seen.get() == H::clock() {
            computed.state.set(State::Fresh);
            return Ok(());
        }
        if state == State::Stale && !dependencies_changed(cx, node)? {
            computed.state.set(State::Fresh);
            computed.clock_seen.set(H::clock());
            return Ok(());
        }
        H::refresh(cx, node, handle)
    })
}

/// Bring computed dependencies up to date, then report whether any
/// dependency's version differs from the one this consumer last saw.
pub fn dependencies_changed<H: Host>(cx: H::Cx<'_>, node: &Rc<Node<H>>) -> Result<bool, H::Error> {
    let deps = &node.reader_state().deps;
    let mut position = 0;
    loop {
        // Signals are compared in place; a computed may run host code to
        // refresh, so it is copied out first.
        let computed = {
            let deps = deps.borrow();
            let Some(link) = deps.get(position) else {
                return Ok(false);
            };
            if !matches!(link.node.role, Role::Computed(_)) {
                if link.version != link.node.version.get() {
                    return Ok(true);
                }
                position += 1;
                continue;
            }
            (
                link.node.clone(),
                H::clone_handle(cx, &link.handle),
                link.version,
            )
        };
        let (dep, handle, seen_version) = computed;
        ensure_uptodate(cx, &dep, &handle)?;
        if seen_version != dep.version.get() {
            return Ok(true);
        }
        position += 1;
    }
}

/// Effects only: a dependency changed after this run read it.
pub fn invalidated_since_read<H: Host>(node: &Node<H>) -> bool {
    node.reader_state().deps.borrow().iter().any(|link| {
        link.version != link.node.version.get()
            || matches!(&link.node.role, Role::Computed(computed) if computed.notified.get())
    })
}

/// Fail if `node` is already evaluating: on this thread it is a cycle;
/// otherwise another thread is running it.
pub fn check_cycle<H: Host>(node: &Rc<Node<H>>) -> Result<(), H::Error> {
    if !node.computed_state().computing.get() {
        return Ok(());
    }
    Err(H::engine_error(if is_evaluating(node) {
        EngineError::Cycle
    } else {
        EngineError::OtherThread
    }))
}

/// Record that `node` is current. A changed or forced outcome gets a new
/// version; otherwise the node only notes the clock it is current at.
pub fn settle<H: Host>(node: &Node<H>, bump: bool) {
    let computed = node.computed_state();
    computed.state.set(State::Fresh);
    let seen = if bump { bump_version(node) } else { H::clock() };
    computed.clock_seen.set(seen);
}

/// After an evaluation failed in a way that must not be cached: the next
/// read retries, even though dependencies were committed.
pub fn must_refresh<H: Host>(node: &Node<H>) {
    let computed = node.computed_state();
    if computed.state.get() < State::MustRefresh {
        computed.state.set(State::MustRefresh);
    }
}

/// Evaluate `node` with dependency tracking (step 2 of a refresh): `f`'s
/// reads become `node`'s dependencies, after a failed evaluation too.
/// `f` must not unwind.
#[inline]
pub fn evaluate<H: Host, T>(
    node: &Rc<Node<H>>,
    f: impl FnOnce() -> Result<T, H::Error>,
) -> Result<T, H::Error> {
    let computed = node.computed_state();
    computed.computing.set(true);
    tracking::start_refresh(node);
    let depth = tracking::push_frame(Some(node.clone()));
    let mut result = f();
    if let Err(error) = tracking::end_frame::<H>(depth) {
        result = Err(error);
    }
    computed.computing.set(false);
    tracking::commit_refresh(node);
    result
}
