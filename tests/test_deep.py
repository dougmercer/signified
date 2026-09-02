"""Tests for explicit deep-resolution helpers."""

from collections import deque

import pytest

from signified import Signal, computed, deep, effect


def test_deep_unref_resolves_supported_containers():
    nested = {
        Signal("key"): [
            Signal(1),
            (Signal(2), {Signal(3)}),
            deque([Signal(4)]),
        ]
    }

    assert deep.unref(nested) == {"key": [1, (2, {3}), deque([4])]}


def test_deep_unref_crosses_multiple_reactive_boundaries():
    assert deep.unref(Signal(Signal(Signal(1)))) == 1


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
