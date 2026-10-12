//! Effects: functions run again whenever something they read changes.

use std::any::Any;
use std::cell::RefCell;
use std::fmt;
use std::rc::Rc;

use signified_engine::{scheduler, tracking, Role};

use crate::host::{catch, unwrap, Error, Node, Owned, Slot};

/// A function that runs once when created, then again after anything it
/// read changes.
///
/// It runs after the change that triggered it has reached every computed,
/// and after the outermost [`batch`](crate::batch). It stops when the
/// `Effect` is dropped or [disposed](Effect::dispose).
///
/// ```
/// use std::cell::Cell;
/// use std::rc::Rc;
/// use signified::{Effect, Signal};
///
/// let name = Signal::new("Ada".to_string());
/// let greetings = Rc::new(Cell::new(0));
/// let effect = Effect::new({
///     let (name, greetings) = (name.clone(), greetings.clone());
///     move || {
///         let _ = format!("Hello, {}!", name.get());
///         greetings.set(greetings.get() + 1);
///     }
/// });
/// assert_eq!(greetings.get(), 1);
/// name.set("Grace".to_string());
/// assert_eq!(greetings.get(), 2);
/// drop(effect);
/// name.set("Edsger".to_string());
/// assert_eq!(greetings.get(), 2);
/// ```
///
/// If the function panics, the panic continues from whatever caused the run
/// (creating the effect, or writing a signal), after other queued effects
/// have run; the effect runs again after the next change to what it read.
pub struct Effect {
    node: Owned,
}

struct EffectSlot<F> {
    function: RefCell<F>,
}

impl<F: FnMut() + 'static> Slot for EffectSlot<F> {
    fn cell(&self) -> &dyn Any {
        unreachable!("effects have no value")
    }

    fn refresh(&self, _: &Rc<Node>) -> Result<(), Error> {
        unreachable!("effects are not computeds")
    }

    fn call(&self) -> Result<(), Error> {
        // Runs of one effect never nest: the queue does not flush inside a
        // flush.
        let mut function = self.function.borrow_mut();
        catch(|| (*function)())
    }
}

impl Effect {
    /// Run `function` now (or when the current batch ends), and again after
    /// anything it read changes.
    pub fn new(function: impl FnMut() + 'static) -> Effect {
        let node: Rc<Node> = Rc::new(signified_engine::Node::new(
            Role::effect(()),
            EffectSlot {
                function: RefCell::new(function),
            },
        ));
        node.effect_state().active.set(true);
        unwrap(scheduler::schedule((), &node));
        Effect {
            node: Owned::new(node),
        }
    }

    /// Stop running, including any run already queued. Safe to repeat.
    pub fn dispose(&self) {
        self.node.rc().effect_state().active.set(false);
        scheduler::discard(self.node.rc());
        tracking::detach_all_deps(self.node.rc());
    }
}

impl fmt::Debug for Effect {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Effect")
            .field("active", &self.node.rc().effect_state().active.get())
            .finish()
    }
}
