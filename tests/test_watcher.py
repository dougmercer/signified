import gc
import weakref

import pytest

from signified import Computed, Signal, Watcher, batch, computed


def test_a_signal_change_is_reported_once():
    s = Signal(1)
    w = Watcher()
    w.watch(s, "s")
    assert w.changed() == []
    s.value = 2
    assert w.changed() == ["s"]
    assert w.changed() == []


def test_setting_an_equal_value_reports_nothing():
    s = Signal(1)
    w = Watcher()
    w.watch(s)
    s.value = 1
    assert w.changed() == []


def test_a_computed_that_recalculates_to_the_same_result_is_not_reported():
    frame = Signal(0)
    held = computed(lambda f: min(f, 10))(frame)
    w = Watcher()
    w.watch(held, "held")
    frame.value = 0
    frame.value = 20
    assert w.changed() == ["held"]
    frame.value = 30
    assert w.changed() == []


def test_changed_brings_only_invalidated_values_up_to_date():
    a, b = Signal(1), Signal(2)
    runs = {"a": 0, "b": 0}

    def double(name, source):
        def run():
            runs[name] += 1
            return source.value * 2

        return Computed(run)

    da, db = double("a", a), double("b", b)
    w = Watcher()
    w.watch(da, "a")
    w.watch(db, "b")
    assert runs == {"a": 1, "b": 1}
    a.value = 5
    assert w.changed() == ["a"]
    assert runs == {"a": 2, "b": 1}


def test_values_sharing_a_key_report_it_once():
    a, b = Signal(1), Signal(2)
    w = Watcher()
    key = object()
    w.watch(a, key)
    w.watch(b, key)
    a.value, b.value = 3, 4
    assert w.changed() == [key]


def test_keys_come_in_the_order_their_values_changed():
    a, b, c = Signal(1), Signal(2), Signal(3)
    w = Watcher()
    for name, s in (("a", a), ("b", b), ("c", c)):
        w.watch(s, name)
    c.value, a.value = 30, 10
    assert w.changed() == ["c", "a"]


def test_a_value_watched_again_after_unwatch_starts_from_its_current_version():
    s = Signal(1)
    w = Watcher()
    w.watch(s, "s")
    s.value = 2
    w.unwatch("s")
    assert w.changed() == []
    assert len(w) == 0
    w.watch(s, "s")
    assert w.changed() == []
    s.value = 3
    assert w.changed() == ["s"]


def test_unwatch_removes_the_observer_from_the_value():
    s = Signal(1)
    w = Watcher()
    w.watch(s, "s")
    assert s._observer_count() == 1
    w.unwatch("s")
    assert s._observer_count() == 0


def test_a_raising_computed_is_reported():
    w = Watcher()
    source = Signal(1)
    guarded = Computed(lambda: 1 / source.value)
    w.watch(guarded, "guarded")
    source.value = 0
    assert w.changed() == ["guarded"]
    with pytest.raises(ZeroDivisionError):
        guarded.value


def test_changes_inside_a_batch_are_reported_after_it():
    a = Signal(1)
    w = Watcher()
    w.watch(a, "a")
    with batch():
        a.value = 2
        a.value = 3
    assert w.changed() == ["a"]


def test_a_plain_value_is_not_watched():
    w = Watcher()
    w.watch(3, "three")
    assert len(w) == 0


def test_a_computed_read_in_between_is_still_reported_once():
    s = Signal(1)
    doubled = Computed(lambda: s.value * 2)
    w = Watcher()
    w.watch(doubled, "d")
    s.value = 2
    assert doubled.value == 4  # the reader refreshes it before the watcher asks
    s.value = 3
    assert w.changed() == ["d"]


def test_a_collected_watcher_leaves_its_values():
    s = Signal(1)
    w = Watcher()
    w.watch(s, "s")
    ref = weakref.ref(w)
    del w
    gc.collect()
    assert ref() is None
    assert s._observer_count() == 0
    s.value = 2  # the walk skips nothing stale


def test_a_watcher_in_a_cycle_with_its_keys_is_collected():
    class Owner:
        pass

    owner = Owner()
    owner.watcher = Watcher()
    s = Signal(1)
    owner.watcher.watch(s, owner)
    ref = weakref.ref(owner)
    del owner
    gc.collect()
    assert ref() is None


def test_many_watches_on_one_value_survive_compaction():
    s = Signal(0)
    watchers = [Watcher() for _ in range(40)]
    for index, w in enumerate(watchers):
        w.watch(s, index)
    for index in range(0, 40, 2):
        watchers[index].unwatch(index)
    s.value = 1
    assert [watchers[index].changed() for index in range(1, 40, 2)] == [[index] for index in range(1, 40, 2)]
    for index in range(1, 40, 2):
        watchers[index].unwatch(index)
    assert s._observer_count() == 0


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_control_flow_errors_from_a_refresh_propagate(error):
    trigger = Signal(False)

    def compute():
        if trigger.value:
            raise error("stop")
        return 1

    w = Watcher()
    w.watch(Computed(compute), "c")
    trigger.value = True
    with pytest.raises(error):
        w.changed()


def test_an_interrupted_changed_loses_no_report():
    a, trigger = Signal(0), Signal(False)

    def compute():
        if trigger.value:
            raise KeyboardInterrupt
        return 1

    w = Watcher()
    w.watch(a, "a")
    w.watch(Computed(compute), "c")
    a.value = 1
    trigger.value = True
    with pytest.raises(KeyboardInterrupt):
        w.changed()
    trigger.value = False
    assert w.changed()[0] == "a"


def test_a_watch_replaced_after_its_invalidation_is_not_reported_for_the_old_one():
    old, first, replacement = Signal(0), Signal(0), Signal(0)
    w = Watcher()
    w.watch(old, "old")
    w.watch(first, "first")
    old.value = 1
    first.value = 1
    w.unwatch("old")
    w.watch(replacement, "replacement")  # takes the old watch's place
    assert w.changed() == ["first"]
    replacement.value = 1
    assert w.changed() == ["replacement"]


def test_keys_keep_their_order_when_a_watch_takes_a_removed_ones_place():
    old, first, replacement = Signal(0), Signal(0), Signal(0)
    w = Watcher()
    w.watch(old, "old")
    w.watch(first, "first")
    old.value = 1
    first.value = 1
    w.unwatch("old")
    w.watch(replacement, "replacement")
    replacement.value = 1
    assert w.changed() == ["first", "replacement"]


def test_a_refresh_that_replaces_its_own_watch_does_not_report_the_replacement():
    trigger, replacement = Signal(False), Signal(100)
    w = Watcher()

    def compute():
        if trigger.value:
            w.unwatch("old")
            w.watch(replacement, "new")
        return trigger.value

    w.watch(Computed(compute), "old")
    trigger.value = True
    assert w.changed() == []
    replacement.value = 101
    assert w.changed() == ["new"]


@pytest.mark.parametrize("every", [1, 4])
def test_unwatching_many_watches_of_one_value_removes_all_their_observers(every):
    s = Signal(0)
    w = Watcher()
    removed, kept = object(), object()
    for index in range(40):
        w.watch(s, kept if every > 1 and index % every == 0 else removed)
    w.unwatch(removed)
    assert len(w) == s._observer_count() == (40 // every if every > 1 else 0)
    s.value = 1
    assert w.changed() == ([kept] if every > 1 else [])
