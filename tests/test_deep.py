"""Tests for explicit deep-resolution helpers."""

from collections import deque

import pytest

from signified import Signal, computed, deep_unref, effect


def test_deep_unref_resolves_supported_containers():
    nested = {
        Signal("key"): [
            Signal(1),
            (Signal(2), {Signal(3)}, frozenset({Signal(4)})),
            deque([Signal(5)], maxlen=2),
        ]
    }

    assert deep_unref(nested) == {"key": [1, (2, {3}, frozenset({4})), deque([5], maxlen=2)]}


def test_deep_unref_crosses_multiple_reactive_boundaries():
    assert deep_unref(Signal(Signal(Signal(1)))) == 1


def test_deep_unref_supports_registered_container_types():
    class Box:
        def __init__(self, values):
            self.values = values

    @deep_unref.register(Box)
    def resolve_box(box, resolve):
        return Box([resolve(value) for value in box.values])

    result = deep_unref(Box([Signal(1), {"nested": Signal(2)}]))

    assert result.values == [1, {"nested": 2}]


def test_deep_unref_reports_cycles():
    cyclic = []
    cyclic.append(cyclic)

    with pytest.raises(ValueError, match="Cycle detected while resolving list"):
        deep_unref(cyclic)


def test_deep_effect_resolves_and_tracks_nested_reactive_values():
    first = Signal(1)
    second = Signal(2)
    config = {"values": [first, {"second": second}]}
    seen = []

    watcher = effect(lambda: seen.append(deep_unref(config)))()
    first.value = 10
    second.value = 20

    assert seen == [
        {"values": [1, {"second": 2}]},
        {"values": [10, {"second": 2}]},
        {"values": [10, {"second": 20}]},
    ]
    watcher.dispose()


def test_deep_unref_is_not_deprecated():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert deep_unref(Signal(1)) == 1


def test_aliases_preserved_in_containers_and_reactive_boundaries():
    shared = [Signal(1)]
    result = deep_unref([shared, Signal(shared), shared])
    assert result[0] is result[1] is result[2]
    assert result[0] is not shared


@pytest.mark.parametrize("make", [lambda a, b: {a: 1, b: 2}, set, frozenset])
def test_resolved_collisions_raise(make):
    a, b = Signal("same"), Signal("same")
    value = make(a, b) if callable(make) and make not in (set, frozenset) else make([a, b])
    with pytest.raises(ValueError, match="collision.*\\$"):
        deep_unref(value)


@pytest.mark.parametrize("make", [lambda a: {a: 1}, lambda a: {a}, lambda a: frozenset({a})])
def test_resolved_unhashable_members_raise(make):
    with pytest.raises(TypeError, match="Unhashable.*\\$"):
        deep_unref(make(Signal([])))


def test_registered_handler_exception_keeps_type_and_path():
    class Box:
        pass

    @deep_unref.register(Box)
    def fail(value, resolve):
        raise LookupError("handler failed")

    with pytest.raises(LookupError) as caught:
        deep_unref([Box()])
    assert any("$[0]" in note for note in caught.value.__notes__)


def test_numpy_preserves_shape_dtype_aliases_and_object_leaves():
    np = pytest.importorskip("numpy")
    numeric = np.array([1, 2])
    assert deep_unref(numeric) is numeric
    objects = np.empty((2,), dtype=object)
    shared = [Signal(1), Signal(2)]
    objects[0] = shared
    objects[1] = shared
    result = deep_unref(objects)
    assert result.shape == (2,)
    assert result.dtype == object
    assert result[0] is result[1]
    assert result[0] == [1, 2]
    scalar = np.empty((), dtype=object)
    scalar[()] = Signal(3)
    assert deep_unref(scalar).item() == 3
    structured = np.empty(1, dtype=[("label", object), ("count", "i4")])
    structured["label"][0] = Signal("resolved")
    structured["count"][0] = 4
    resolved = deep_unref(structured)
    assert resolved.dtype == structured.dtype
    assert resolved["label"][0] == "resolved"
    assert resolved["count"][0] == 4
