"""Tests for explicit deep-resolution helpers."""

from collections import deque

import pytest

from signified import Signal, computed, deep, effect


def test_deep_unref_resolves_supported_containers():
    nested = {
        Signal("key"): [
            Signal(1),
            (Signal(2), {Signal(3)}, frozenset({Signal(4)})),
            deque([Signal(5)], maxlen=2),
        ]
    }

    assert deep.unref(nested) == {"key": [1, (2, {3}, frozenset({4})), deque([5], maxlen=2)]}


def test_deep_unref_crosses_multiple_reactive_boundaries():
    assert deep.unref(Signal(Signal(Signal(1)))) == 1


def test_deep_unref_leaves_unregistered_iterables_opaque():
    class Box:
        def __init__(self, values):
            self.values = values

        def __iter__(self):
            return iter(self.values)

    nested = Signal(1)
    box = Box([nested])

    assert deep.unref(box) is box


def test_deep_unref_supports_registered_container_types():
    class Box:
        def __init__(self, values):
            self.values = values

    @deep.register(Box)
    def resolve_box(box, resolve):
        return Box([resolve(value) for value in box.values])

    result = deep.unref(Box([Signal(1), {"nested": Signal(2)}]))

    assert result.values == [1, {"nested": 2}]


def test_deep_unref_reports_cycles():
    cyclic = []
    cyclic.append(cyclic)

    with pytest.raises(ValueError, match="Cycle detected while resolving list"):
        deep.unref(cyclic)


def test_computed_only_shallowly_resolves_arguments():
    nested = Signal(1)
    container = {"nested": nested}

    result = computed(lambda value: value)(container)

    assert result.value is container
    nested.value = 2
    assert result.value is container


def test_effect_only_shallowly_resolves_arguments():
    nested = Signal(1)
    container = {"nested": nested}
    seen = []

    watcher = effect(seen.append)(container)
    nested.value = 2

    assert seen == [container]
    watcher.dispose()


def test_deep_effect_resolves_and_tracks_nested_reactive_values():
    first = Signal(1)
    second = Signal(2)
    config = {"values": [first, {"second": second}]}
    seen = []

    watcher = deep.effect(seen.append)(config)
    first.value = 10
    second.value = 20

    assert seen == [
        {"values": [1, {"second": 2}]},
        {"values": [10, {"second": 2}]},
        {"values": [10, {"second": 20}]},
    ]
    watcher.dispose()


def test_deep_unref_compatibility_alias_is_deprecated():
    from signified import deep_unref

    with pytest.deprecated_call(match=r"use deep\.unref"):
        assert deep_unref(Signal(1)) == 1
