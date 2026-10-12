//! Propagation, laziness and cutoff, as the Python library's tests check them.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use signified::{batch, is_tracking, untracked, Computed, Effect, Signal};

/// A counter shared with a closure.
#[derive(Clone, Default)]
struct Runs(Rc<Cell<u32>>);

impl Runs {
    fn hit(&self) {
        self.0.set(self.0.get() + 1);
    }

    fn take(&self) -> u32 {
        self.0.replace(0)
    }
}

#[test]
fn computed_is_lazy_and_cached() {
    let source = Signal::new(1);
    let runs = Runs::default();
    let doubled = Computed::new({
        let (source, runs) = (source.clone(), runs.clone());
        move || {
            runs.hit();
            source.get() * 2
        }
    });
    assert_eq!(runs.take(), 0, "nothing runs before the first read");
    assert_eq!(doubled.get(), 2);
    assert_eq!(doubled.get(), 2);
    assert_eq!(runs.take(), 1, "a second read uses the cached value");
    source.set(5);
    assert_eq!(runs.take(), 0, "a write does not evaluate");
    assert_eq!(doubled.get(), 10);
    assert_eq!(runs.take(), 1);
}

#[test]
fn setting_an_equal_value_does_nothing() {
    let source = Signal::new(3);
    let runs = Runs::default();
    let _effect = Effect::new({
        let (source, runs) = (source.clone(), runs.clone());
        move || {
            source.get();
            runs.hit();
        }
    });
    assert_eq!(runs.take(), 1);
    source.set(3);
    assert_eq!(runs.take(), 0);
    source.set(4);
    assert_eq!(runs.take(), 1);
}

#[test]
fn an_unchanged_value_stops_propagation() {
    let source = Signal::new(4);
    let parity = Computed::new({
        let source = source.clone();
        move || source.get() % 2
    });
    let runs = Runs::default();
    let label = Computed::new({
        let (parity, runs) = (parity.clone(), runs.clone());
        move || {
            runs.hit();
            if parity.get() == 0 {
                "even"
            } else {
                "odd"
            }
        }
    });
    assert_eq!(label.get(), "even");
    assert_eq!(runs.take(), 1);
    source.set(6);
    assert_eq!(label.get(), "even");
    assert_eq!(
        runs.take(),
        0,
        "parity did not change, so label did not rerun"
    );
    source.set(7);
    assert_eq!(label.get(), "odd");
    assert_eq!(runs.take(), 1);
}

#[test]
fn a_custom_equality_decides_what_counts_as_a_change() {
    let source = Signal::new(1.0_f64);
    let rounded = Computed::new_with_equal(
        {
            let source = source.clone();
            move || source.get()
        },
        |a: &f64, b: &f64| (a - b).abs() < 0.5,
    );
    let runs = Runs::default();
    let downstream = Computed::new({
        let (rounded, runs) = (rounded.clone(), runs.clone());
        move || {
            runs.hit();
            rounded.get()
        }
    });
    assert_eq!(downstream.get(), 1.0);
    source.set(1.2);
    assert_eq!(downstream.get(), 1.0, "the previous value is kept");
    source.set(2.0);
    assert_eq!(downstream.get(), 2.0);
    assert_eq!(runs.take(), 2);
}

#[test]
fn diamond_runs_each_node_once_per_change() {
    let source = Signal::new(1);
    let runs = Runs::default();
    let left = Computed::new({
        let source = source.clone();
        move || source.get() + 1
    });
    let right = Computed::new({
        let source = source.clone();
        move || source.get() * 10
    });
    let joined = Computed::new({
        let (left, right, runs) = (left.clone(), right.clone(), runs.clone());
        move || {
            runs.hit();
            left.get() + right.get()
        }
    });
    assert_eq!(joined.get(), 12);
    for value in 2..10 {
        source.set(value);
        assert_eq!(joined.get(), value + 1 + value * 10);
    }
    assert_eq!(runs.take(), 9);
}

#[test]
fn dependencies_follow_the_branch_taken() {
    let use_a = Signal::new(true);
    let a = Signal::new("a");
    let b = Signal::new("b");
    let runs = Runs::default();
    let picked = Computed::new({
        let (use_a, a, b, runs) = (use_a.clone(), a.clone(), b.clone(), runs.clone());
        move || {
            runs.hit();
            if use_a.get() {
                a.get()
            } else {
                b.get()
            }
        }
    });
    assert_eq!(picked.get(), "a");
    b.set("B");
    assert_eq!(picked.get(), "a");
    assert_eq!(
        runs.take(),
        1,
        "b was not read, so writing it changes nothing"
    );
    use_a.set(false);
    assert_eq!(picked.get(), "B");
    a.set("A");
    assert_eq!(picked.get(), "B");
    assert_eq!(runs.take(), 1, "a is no longer read");
}

#[test]
fn effects_run_after_changes_and_stop_when_dropped() {
    let source = Signal::new(0);
    let seen = Rc::new(RefCell::new(Vec::new()));
    let effect = Effect::new({
        let (source, seen) = (source.clone(), seen.clone());
        move || seen.borrow_mut().push(source.get())
    });
    source.set(1);
    source.set(2);
    effect.dispose();
    source.set(3);
    let again = Effect::new({
        let (source, seen) = (source.clone(), seen.clone());
        move || seen.borrow_mut().push(source.get() * 100)
    });
    drop(again);
    source.set(4);
    assert_eq!(*seen.borrow(), vec![0, 1, 2, 300]);
}

#[test]
fn effects_see_a_consistent_graph() {
    let source = Signal::new(1);
    let doubled = Computed::new({
        let source = source.clone();
        move || source.get() * 2
    });
    let seen = Rc::new(RefCell::new(Vec::new()));
    let _effect = Effect::new({
        let (source, doubled, seen) = (source.clone(), doubled.clone(), seen.clone());
        move || seen.borrow_mut().push((source.get(), doubled.get()))
    });
    source.set(2);
    assert_eq!(*seen.borrow(), vec![(1, 2), (2, 4)]);
}

#[test]
fn batch_runs_each_effect_once() {
    let a = Signal::new(1);
    let b = Signal::new(2);
    let runs = Runs::default();
    let _effect = Effect::new({
        let (a, b, runs) = (a.clone(), b.clone(), runs.clone());
        move || {
            a.get();
            b.get();
            runs.hit();
        }
    });
    runs.take();
    let returned = batch(|| {
        a.set(10);
        batch(|| b.set(20));
        assert_eq!(runs.take(), 0, "nothing runs inside a batch");
        "done"
    });
    assert_eq!(returned, "done");
    assert_eq!(runs.take(), 1);
}

#[test]
fn an_effect_can_write_what_it_does_not_read() {
    let source = Signal::new(1);
    let mirror = Signal::new(0);
    let _effect = Effect::new({
        let (source, mirror) = (source.clone(), mirror.clone());
        move || mirror.set(source.get())
    });
    source.set(5);
    assert_eq!(mirror.get(), 5);
}

#[test]
fn untracked_reads_are_not_dependencies() {
    let tracked = Signal::new(1);
    let ignored = Signal::new(10);
    let runs = Runs::default();
    let sum = Computed::new({
        let (tracked, ignored, runs) = (tracked.clone(), ignored.clone(), runs.clone());
        move || {
            runs.hit();
            assert!(is_tracking());
            let ignored = untracked(|| {
                assert!(!is_tracking());
                ignored.get()
            });
            tracked.get() + ignored
        }
    });
    assert!(!is_tracking());
    assert_eq!(sum.get(), 11);
    ignored.set(20);
    assert_eq!(sum.get(), 11);
    tracked.set(2);
    assert_eq!(sum.get(), 22);
    assert_eq!(runs.take(), 2);
}

#[test]
fn update_notifies_after_an_in_place_change() {
    let items = Signal::new(vec![1, 2]);
    let total = Computed::new({
        let items = items.clone();
        move || items.with(|items| items.iter().sum::<i32>())
    });
    assert_eq!(total.get(), 3);
    items.update(|items| items.push(3));
    assert_eq!(total.get(), 6);
}

#[test]
fn values_need_not_be_clone_or_copy() {
    struct Mesh {
        vertices: Vec<[f32; 3]>,
    }
    let mesh = Signal::new(Mesh {
        vertices: vec![[0.0; 3]; 4],
    });
    let count = Computed::new({
        let mesh = mesh.clone();
        move || mesh.with(|mesh| mesh.vertices.len())
    });
    assert_eq!(count.get(), 4);
    mesh.update(|mesh| mesh.vertices.push([1.0; 3]));
    assert_eq!(count.get(), 5);
}

#[test]
fn a_freed_computed_unsubscribes() {
    let source = Signal::new(1);
    let runs = Runs::default();
    let computed = Computed::new({
        let (source, runs) = (source.clone(), runs.clone());
        move || {
            runs.hit();
            source.get()
        }
    });
    let _effect = Effect::new({
        let computed = computed.clone();
        move || {
            computed.get();
        }
    });
    drop(computed);
    source.set(2);
    assert_eq!(runs.take(), 2, "the effect keeps the computed alive");
    drop(_effect);
    source.set(3);
    assert_eq!(runs.take(), 0);
}

#[test]
fn deep_chains_do_not_overflow_the_stack() {
    let source = Signal::new(0_i64);
    let mut tail = Computed::new({
        let source = source.clone();
        move || source.get()
    });
    for _ in 0..20_000 {
        let previous = tail.clone();
        tail = Computed::new(move || previous.get() + 1);
    }
    // The first read evaluates every node, nested, as does a read after a
    // change at the far end.
    assert_eq!(tail.get(), 20_000);
    source.set(5);
    assert_eq!(tail.get(), 20_005);
    // Freeing it drops each node from the one after it, without recursing.
    drop(tail);
}
