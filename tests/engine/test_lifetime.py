"""Lifetime and garbage-collection behavior: the riskiest part of a Rust core."""

import gc
import weakref

from signified import Computed, Signal


def test_unreferenced_computed_is_freed_and_unsubscribed():
    s = Signal(1)
    c = s + 1
    assert c.value == 2
    ref = weakref.ref(c)
    del c
    gc.collect()
    assert ref() is None
    s.value = 2  # must not touch the freed node
    assert s._observer_count() == 0


def test_object_and_closure_cycle_is_collected():
    class Holder:
        pass

    def build():
        h = Holder()
        h.n = Signal(1)
        h.c = Computed(lambda: h.n.value + 1)  # closure -> h -> c -> closure
        assert h.c.value == 2
        return weakref.ref(h), weakref.ref(h.c)

    holder_ref, computed_ref = build()
    gc.collect()
    assert holder_ref() is None
    assert computed_ref() is None


def test_many_cycles_collect_in_any_order_without_crashing():
    class Holder:
        pass

    refs = []
    for i in range(500):
        h = Holder()
        h.n = Signal(i)
        h.doubled = h.n * 2
        h.c = Computed(lambda h=h: h.doubled.value + h.n.value)
        assert h.c.value == 3 * i
        refs.append(weakref.ref(h))
    del h
    gc.collect()
    assert all(r() is None for r in refs)
    survivor = Signal(1)
    assert (survivor + 1).value == 2


def test_python_observers_are_held_weakly():
    s = Signal(5)

    class Appender:
        def update(self) -> None:
            raise AssertionError("dead observer should never be notified")

    appender = Appender()
    ref = weakref.ref(appender)
    s.subscribe(appender)
    del appender
    gc.collect()
    assert ref() is None
    s.value = 6
    assert s._observer_count() == 0


def test_engine_survives_garbage_collection_at_every_allocation():
    thresholds = gc.get_threshold()
    gc.set_threshold(1, 1, 1)
    try:
        s = Signal(0)
        leaves = [Computed(lambda i=i: s.value + i) for i in range(50)]
        total = Computed(lambda: sum(leaf.value for leaf in leaves))
        for step in range(1, 20):
            s.value = step
            assert total.value == 50 * step + sum(range(50))
    finally:
        gc.set_threshold(*thresholds)


def test_graph_built_on_another_thread_is_usable_here():
    import threading

    box = {}

    def build():
        box["source"] = Signal(1)
        box["doubled"] = box["source"] * 2
        box["doubled"].value

    thread = threading.Thread(target=build)
    thread.start()
    thread.join()
    box["source"].value = 5
    assert box["doubled"].value == 10
    box.clear()
    gc.collect()


def test_dead_observers_release_their_subscription():
    import sys

    s = Signal(0)

    class Observer:
        def update(self) -> None:
            pass

    observer = Observer()
    s.subscribe(observer)
    (reference,) = weakref.getweakrefs(observer)
    held = sys.getrefcount(reference)
    del observer
    gc.collect()
    # Only this test's reference (and getrefcount's argument) remain.
    assert sys.getrefcount(reference) == held - 1


def test_cycle_through_a_signal_at_context_is_collected():
    s = Signal(None)
    context = s.at(1)
    s.value = context
    ref = weakref.ref(s)
    del s, context
    gc.collect()
    assert ref() is None


def test_cycle_through_a_name_is_collected():
    class Name(str):
        pass

    s = Signal(0)
    name = Name("label")
    name.owner = s
    s.with_name(name)
    ref = weakref.ref(s)
    del s, name
    gc.collect()
    assert ref() is None
