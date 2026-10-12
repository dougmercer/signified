//! Computeds: values derived from signals and other computeds, recomputed
//! lazily when something they read changed.

use std::any::Any;
use std::cell::RefCell;
use std::fmt;
use std::marker::PhantomData;
use std::rc::Rc;

use signified_engine::refresh::{check_cycle, ensure_uptodate, evaluate, must_refresh, settle};
use signified_engine::{tracking, Role, State};

use crate::host::{catch, unwrap, Error, Node, Owned, Slot};

/// A value computed from other reactive values.
///
/// The function runs when the value is first read, and again when it is
/// read after something the last run read has changed. Whatever it reads
/// becomes its dependencies, so they can differ from run to run. When it
/// produces a value equal to the previous one, computeds and effects that
/// read this one are not run again.
///
/// Cloning a `Computed` makes another handle to the same value. A computed
/// lives while a handle to it, or a computed or effect that read it, does.
///
/// ```
/// use signified::{Computed, Signal};
///
/// let width = Signal::new(2.0);
/// let height = Signal::new(3.0);
/// let area = Computed::new({
///     let (width, height) = (width.clone(), height.clone());
///     move || width.get() * height.get()
/// });
/// assert_eq!(area.get(), 6.0);
/// width.set(4.0);
/// assert_eq!(area.get(), 12.0);
/// ```
///
/// A function that panics leaves the computed to run again on its next
/// read; the panic continues where the value was read. A computed that reads
/// itself, directly or through others, panics with a cycle error.
pub struct Computed<T: 'static> {
    node: Owned,
    value: PhantomData<T>,
}

struct ComputedSlot<T, F, E> {
    value: RefCell<Option<T>>,
    function: F,
    equal: E,
}

impl<T, F, E> Slot for ComputedSlot<T, F, E>
where
    T: 'static,
    F: Fn() -> T + 'static,
    E: Fn(&T, &T) -> bool + 'static,
{
    fn cell(&self) -> &dyn Any {
        &self.value
    }

    fn refresh(&self, node: &Rc<Node>) -> Result<(), Error> {
        check_cycle(node)?;
        let forced = node.computed_state().state.get() == State::MustRefresh;
        let next = match evaluate(node, || catch(&self.function)) {
            Ok(next) => next,
            Err(error) => {
                must_refresh(node);
                return Err(error);
            }
        };
        // User code (the equality, and dropping a value) runs only where the
        // engine's state is complete: before `settle` the node is still
        // stale, and is evaluated again if this panics.
        let changed = match &*self.value.borrow() {
            Some(previous) => !(self.equal)(previous, &next),
            None => true,
        };
        let discarded = if changed {
            self.value
                .try_borrow_mut()
                .map(|mut value| value.replace(next))
                .expect("a computed's value was borrowed (by `with`) while it was recomputed")
        } else {
            Some(next)
        };
        settle(node, changed || forced);
        drop(discarded);
        Ok(())
    }

    fn call(&self) -> Result<(), Error> {
        unreachable!("computeds are not effects")
    }
}

impl<T: 'static> Computed<T> {
    /// A computed whose value is `function()`. A new value equal to the
    /// previous one (by `PartialEq`) counts as unchanged.
    pub fn new(function: impl Fn() -> T + 'static) -> Computed<T>
    where
        T: PartialEq,
    {
        Computed::new_with_equal(function, T::eq)
    }

    /// A computed whose value is `function()`, where `equal(previous, new)`
    /// decides whether a new value counts as unchanged.
    pub fn new_with_equal(
        function: impl Fn() -> T + 'static,
        equal: impl Fn(&T, &T) -> bool + 'static,
    ) -> Computed<T> {
        let node: Rc<Node> = Rc::new(signified_engine::Node::new(
            Role::computed(()),
            ComputedSlot {
                value: RefCell::new(None),
                function,
                equal,
            },
        ));
        Computed {
            node: Owned::new(node),
            value: PhantomData,
        }
    }

    fn cell(&self) -> &RefCell<Option<T>> {
        self.node
            .rc()
            .payload
            .cell()
            .downcast_ref()
            .expect("a computed's slot holds its type")
    }

    /// The current value, recomputed first if something it read changed.
    /// Inside a computed or effect, the read makes it depend on this one.
    pub fn get(&self) -> T
    where
        T: Clone,
    {
        self.with(T::clone)
    }

    /// Call `f` with the current value, as a read like [`get`](Self::get).
    ///
    /// Panics if `f` causes this computed to be recomputed (by writing a
    /// signal it reads and then reading it).
    pub fn with<R>(&self, f: impl FnOnce(&T) -> R) -> R {
        let refreshed = ensure_uptodate((), self.node.rc(), &());
        // Register the read even when the refresh failed, so the reader
        // runs again.
        tracking::track_read(self.node.rc(), || ());
        unwrap(refreshed);
        let value = self.cell().borrow();
        f(value.as_ref().expect("a current computed has a value"))
    }
}

impl<T: 'static> Clone for Computed<T> {
    fn clone(&self) -> Self {
        Computed {
            node: self.node.clone(),
            value: PhantomData,
        }
    }
}

impl<T: fmt::Debug + 'static> fmt::Debug for Computed<T> {
    /// The value as of the last evaluation, without evaluating.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.cell().try_borrow() {
            Ok(value) => match value.as_ref() {
                Some(value) => f.debug_tuple("Computed").field(value).finish(),
                None => f.write_str("Computed(<not evaluated>)"),
            },
            Err(_) => f.write_str("Computed(<borrowed>)"),
        }
    }
}
