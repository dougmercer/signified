"""Object identity, grouped reporting, and removal through watch-slot reuse."""

import gc
import weakref

import pytest

from signified import Computed, Signal, Watcher


def test_identity_keys_need_neither_hash_nor_equality():
    class Key:
        def __hash__(self):
            raise AssertionError("hash called")

        def __eq__(self, other):
            raise AssertionError("equality called")

    source = Signal(0)
    watcher = Watcher()
    keys = [Key(), Key(), []]
    for key in keys:
        watcher.watch(source, key)
    source.value = 1
    assert [id(key) for key in watcher.changed()] == [id(key) for key in keys]
    for key in keys:
        watcher.unwatch(key)
    assert len(watcher) == source._observer_count() == 0


def test_equal_but_distinct_string_keys_stay_separate():
    keys = ["".join(["row", "123"]) for _ in range(3)]
    assert len({id(key) for key in keys}) == 3
    source = Signal(0)
    watcher = Watcher()
    watcher.watch(source, keys[0])
    watcher.watch(source, keys[1])
    source.value = 1
    changed = watcher.changed()
    assert [id(key) for key in changed] == [id(key) for key in keys[:2]]
    watcher.unwatch(keys[2])
    assert len(watcher) == 2
    watcher.unwatch(keys[0])
    source.value = 2
    assert watcher.changed()[0] is keys[1]
    assert len(watcher) == 1


def test_index_survives_slot_reuse_and_bulk_compaction():
    watcher = Watcher()
    sources = [Signal(0) for _ in range(4)]
    keys = [object() for _ in range(40)]
    for _ in range(8):
        for i, key in enumerate(keys):
            for source in sources[: 1 + i % 4]:
                watcher.watch(source, key)
        for key in keys[::2]:
            watcher.unwatch(key)
        for key in keys[1::2]:
            watcher.unwatch(key)
        assert len(watcher) == 0
        assert all(source._observer_count() == 0 for source in sources)


def test_removing_a_key_releases_it_even_when_the_watcher_lives():
    class Key:
        pass

    watcher = Watcher()
    source = Signal(0)
    key = Key()
    reference = weakref.ref(key)
    watcher.watch(source, key)
    watcher.unwatch(key)
    del key
    gc.collect()
    assert reference() is None
    assert len(watcher) == 0


def test_failed_registration_does_not_remove_existing_watches_or_retain_new_keys():
    class Key:
        pass

    watcher = Watcher()
    source = Signal(0)
    existing = Key()
    watcher.watch(source, existing)

    def interrupt():
        raise KeyboardInterrupt

    for key in (existing, Key()):
        with pytest.raises(KeyboardInterrupt):
            watcher.watch(Computed(interrupt), key)
    reference = weakref.ref(key)
    del key
    gc.collect()
    assert reference() is None
    assert len(watcher) == 1
    source.value = 1
    assert watcher.changed() == [existing]


def test_unchanged_oldest_watch_can_deduplicate_changed_siblings():
    oldest, a, b = Signal(0), Signal(0), Signal(0)
    watcher, key = Watcher(), object()
    for node in (oldest, a, b):
        watcher.watch(node, key)
    for step in range(1, 5):
        a.value = step
        b.value = step
        assert watcher.changed() == [key]
        assert watcher.changed() == []


def test_oldest_is_registration_order_even_when_slot_indices_go_backwards():
    watcher, old, a, b = Watcher(), Signal(0), Signal(0), Signal(0)
    old_key, key = object(), object()
    watcher.watch(old, old_key)
    watcher.watch(a, key)
    watcher.unwatch(old_key)
    watcher.watch(b, key)
    a.value = b.value = 1
    assert watcher.changed() == [key]
    watcher.unwatch(key)
    assert a._observer_count() == b._observer_count() == 0


def test_refresh_appends_same_key_then_reentrant_empty_poll_does_not_consume_it():
    trigger, later = Signal(0), Signal(0)
    watcher, key = Watcher(), object()

    def compute():
        version = trigger.value
        if version:
            watcher.watch(later, key)
            assert watcher.changed() == []
        return version

    current = Computed(compute)
    watcher.watch(current, key)
    trigger.value = 1
    assert watcher.changed() == [key]
    assert current.value == 1
    later.value = 1
    assert watcher.changed() == [key]


@pytest.mark.parametrize("interrupt", [False, True])
def test_refresh_removes_and_recreates_same_key_group(interrupt):
    old, trigger, new_a, new_b = (Signal(0) for _ in range(4))
    watcher, key = Watcher(), object()
    armed = [False]

    def compute():
        version = trigger.value
        if armed[0]:
            armed[0] = False
            watcher.unwatch(key)
            watcher.watch(new_a, key)
            watcher.watch(new_b, key)
            if interrupt:
                raise KeyboardInterrupt
        return version

    watcher.watch(old, key)
    watcher.watch(Computed(compute), key)
    armed[0] = True
    old.value = trigger.value = 1
    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            watcher.changed()
    assert watcher.changed() == []
    new_a.value = new_b.value = 1
    assert watcher.changed() == [key]
    assert watcher.changed() == []


def test_adding_a_value_to_a_group_keeps_its_existing_pending_change():
    first, second = Signal(0), Signal(0)
    watcher, key = Watcher(), object()
    watcher.watch(first, key)
    first.value = 1
    watcher.watch(second, key)
    assert len(watcher) == 2
    assert watcher.changed() == [key]
    watcher.unwatch(key)
    assert len(watcher) == 0
    assert first._observer_count() == second._observer_count() == 0
