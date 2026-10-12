//! Cycles and panics leave the graph usable.

use std::cell::{Cell, RefCell};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::rc::Rc;

use signified::{batch, is_tracking, untracked, Computed, Effect, Signal};

/// The message of the panic `f` raises.
fn panic_message(f: impl FnOnce()) -> String {
    let payload = catch_unwind(AssertUnwindSafe(f)).expect_err("expected a panic");
    if let Some(message) = payload.downcast_ref::<String>() {
        return message.clone();
    }
    payload
        .downcast_ref::<&str>()
        .map(|message| message.to_string())
        .unwrap_or_default()
}

#[test]
fn a_cycle_panics_and_can_be_broken() {
    let closed = Signal::new(true);
    let slot: Rc<RefCell<Option<Computed<i32>>>> = Rc::default();
    let looped = Computed::new({
        let (closed, slot) = (closed.clone(), slot.clone());
        move || {
            if closed.get() {
                slot.borrow().as_ref().map_or(0, Computed::get) + 1
            } else {
                1
            }
        }
    });
    *slot.borrow_mut() = Some(looped.clone());
    let message = panic_message(|| {
        looped.get();
    });
    assert!(message.contains("Cycle detected"), "{message}");
    assert!(!is_tracking(), "no tracking frame is left behind");
    closed.set(false);
    assert_eq!(looped.get(), 1);
    slot.borrow_mut().take();
}

#[test]
fn a_panicking_computed_runs_again_on_the_next_read() {
    let source = Signal::new(0);
    let runs = Rc::new(Cell::new(0));
    let inverse = Computed::new({
        let (source, runs) = (source.clone(), runs.clone());
        move || {
            runs.set(runs.get() + 1);
            let value = source.get();
            assert!(value != 0, "division by zero");
            100 / value
        }
    });
    let doubled = Computed::new({
        let inverse = inverse.clone();
        move || inverse.get() * 2
    });
    assert!(panic_message(|| {
        doubled.get();
    })
    .contains("division by zero"));
    assert!(panic_message(|| {
        doubled.get();
    })
    .contains("division by zero"));
    assert_eq!(runs.get(), 2, "a panic is not cached");
    source.set(5);
    assert_eq!(doubled.get(), 40);
    source.set(0);
    assert!(panic_message(|| {
        inverse.get();
    })
    .contains("division by zero"));
    source.set(10);
    assert_eq!(doubled.get(), 20);
    assert!(!is_tracking());
}

#[test]
fn a_panicking_effect_does_not_stop_the_others() {
    let source = Signal::new(1);
    let seen = Rc::new(RefCell::new(Vec::new()));
    let _fragile = Effect::new({
        let source = source.clone();
        move || assert!(source.get() < 10, "too big")
    });
    let _sturdy = Effect::new({
        let (source, seen) = (source.clone(), seen.clone());
        move || seen.borrow_mut().push(source.get())
    });
    assert!(panic_message(|| source.set(50)).contains("too big"));
    assert_eq!(*seen.borrow(), vec![1, 50]);
    source.set(2);
    assert_eq!(*seen.borrow(), vec![1, 50, 2]);
}

#[test]
fn a_panic_in_a_batch_leaves_later_writes_working() {
    let source = Signal::new(1);
    let seen = Rc::new(RefCell::new(Vec::new()));
    let _effect = Effect::new({
        let (source, seen) = (source.clone(), seen.clone());
        move || seen.borrow_mut().push(source.get())
    });
    let message = panic_message(|| {
        batch(|| {
            source.set(2);
            panic!("inside the batch");
        })
    });
    assert_eq!(message, "inside the batch");
    // The deferred run happens at the next flush.
    source.set(3);
    assert_eq!(*seen.borrow(), vec![1, 3]);
}

#[test]
fn a_panic_inside_untracked_restores_tracking() {
    let source = Signal::new(1);
    let fragile = Computed::new({
        let source = source.clone();
        move || {
            untracked(|| {
                if source.get() == 2 {
                    panic!("untracked panic");
                }
            });
            assert!(is_tracking());
            source.get()
        }
    });
    assert_eq!(fragile.get(), 1);
    source.set(2);
    assert!(panic_message(|| {
        fragile.get();
    })
    .contains("untracked panic"));
    assert!(!is_tracking());
    source.set(3);
    assert_eq!(fragile.get(), 3);
}

#[test]
fn an_effect_that_keeps_triggering_itself_is_stopped() {
    let counter = Signal::new(0);
    let message = panic_message(|| {
        let counter = counter.clone();
        let effect = Effect::new(move || counter.set(counter.get() + 1));
        drop(effect);
    });
    assert!(message.contains("did not settle"), "{message}");
}

#[test]
fn writing_a_signal_while_reading_it_with_with_panics() {
    let source = Signal::new(1);
    let message = panic_message(|| source.with(|_| source.set(2)));
    assert!(message.contains("borrow"), "{message}");
    assert_eq!(source.get(), 1);
}
