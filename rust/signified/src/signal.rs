//! Signals: values you set, which computeds and effects read.

use std::any::Any;
use std::cell::RefCell;
use std::fmt;
use std::marker::PhantomData;
use std::rc::Rc;

use signified_engine::runtime::bump_version;
use signified_engine::{invalidation, tracking, Role};

use crate::host::{unwrap, Error, Node, Owned, Slot};

/// A value that computeds and effects depend on when they read it.
///
/// Cloning a `Signal` makes another handle to the same value. A signal lives
/// while a handle to it, or a computed or effect that read it, does.
///
/// ```
/// use signified::Signal;
///
/// let count = Signal::new(1);
/// count.set(2);
/// assert_eq!(count.get(), 2);
/// count.update(|count| *count += 1);
/// assert_eq!(count.get(), 3);
/// ```
pub struct Signal<T: 'static> {
    node: Owned,
    value: PhantomData<T>,
}

struct SignalSlot<T> {
    value: RefCell<T>,
}

impl<T: 'static> Slot for SignalSlot<T> {
    fn cell(&self) -> &dyn Any {
        &self.value
    }

    fn refresh(&self, _: &Rc<Node>) -> Result<(), Error> {
        unreachable!("signals are never refreshed")
    }

    fn call(&self) -> Result<(), Error> {
        unreachable!("signals are not effects")
    }
}

impl<T: 'static> Signal<T> {
    /// A signal holding `value`.
    pub fn new(value: T) -> Signal<T> {
        let node: Rc<Node> = Rc::new(signified_engine::Node::new(
            Role::Signal,
            SignalSlot {
                value: RefCell::new(value),
            },
        ));
        Signal {
            node: Owned::new(node),
            value: PhantomData,
        }
    }

    fn cell(&self) -> &RefCell<T> {
        self.node
            .rc()
            .payload
            .cell()
            .downcast_ref()
            .expect("a signal's slot holds its type")
    }

    /// The current value. Inside a computed or effect, the read makes it
    /// depend on this signal.
    pub fn get(&self) -> T
    where
        T: Clone,
    {
        self.with(T::clone)
    }

    /// Call `f` with the current value, as a read like [`get`](Self::get).
    ///
    /// Panics if `f` writes this signal.
    pub fn with<R>(&self, f: impl FnOnce(&T) -> R) -> R {
        tracking::track_read(self.node.rc(), || ());
        f(&self.cell().borrow())
    }

    /// Store `value`. If it differs from the current value, computeds that
    /// read this signal go stale and effects that read it run.
    pub fn set(&self, value: T)
    where
        T: PartialEq,
    {
        if *self.cell().borrow() == value {
            return;
        }
        self.replace(value);
    }

    /// Store `value` and notify, whether or not it differs from the current
    /// value. Returns the previous value.
    pub fn replace(&self, value: T) -> T {
        let previous = self.cell().replace(value);
        self.changed();
        previous
    }

    /// Change the value in place, then notify as if it changed.
    pub fn update(&self, f: impl FnOnce(&mut T)) {
        f(&mut self.cell().borrow_mut());
        self.changed();
    }

    fn changed(&self) {
        bump_version(&**self.node.rc());
        unwrap(invalidation::notify((), self.node.rc()));
    }
}

impl<T: 'static> Clone for Signal<T> {
    fn clone(&self) -> Self {
        Signal {
            node: self.node.clone(),
            value: PhantomData,
        }
    }
}

impl<T: fmt::Debug + 'static> fmt::Debug for Signal<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.cell().try_borrow() {
            Ok(value) => f.debug_tuple("Signal").field(&*value).finish(),
            Err(_) => f.write_str("Signal(<borrowed>)"),
        }
    }
}
