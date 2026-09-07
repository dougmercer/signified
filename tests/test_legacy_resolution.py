"""Compatibility while unregistered iterable traversal is deprecated."""

import warnings

import pytest

from signified import Computed, Signal, computed, deep_unref, effect, unref


class Box:
    def __init__(self, values):
        self.values = list(values)

    def __iter__(self):
        return iter(self.values)


def test_unregistered_iterable_still_resolves_with_removal_warning():
    source = Box([Signal(1), {"x": Signal(2)}])
    with pytest.deprecated_call(match=r"removed in 0\.6\.0.*deep_unref.register"):
        result = deep_unref(source)
    assert isinstance(result, Box)
    assert result.values == [1, {"x": 2}]


def test_list_subclasses_keep_legacy_reconstruction():
    class Items(list):
        pass

    with pytest.deprecated_call(match="Items"):
        result = deep_unref(Items([Signal(1)]))
    assert type(result) is Items
    assert result == [1]


def test_unsupported_constructor_returns_original_without_consuming_generator():
    source = (item for item in [Signal(1)])
    with pytest.deprecated_call(match="removed in 0.6.0"):
        assert deep_unref(source) is source
    assert isinstance(next(source), Signal)


def test_child_type_error_is_not_hidden_by_constructor_fallback():
    class Broken:
        pass

    @deep_unref.register(Broken)
    def resolve_broken(value, resolve):
        raise TypeError("child failed")

    with pytest.deprecated_call(), pytest.raises(TypeError, match="child failed"):
        deep_unref(Box([Broken()]))


def test_registered_iterable_needs_no_deprecation_warning():
    class Registered(Box):
        pass

    @deep_unref.register(Registered)
    def resolve_box(value, resolve):
        return Registered([resolve(child) for child in value.values])

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = deep_unref(Registered([Signal(1)]))
    assert result.values == [1]


def test_numpy_subclass_keeps_legacy_array_handling():
    np = pytest.importorskip("numpy")

    class Array(np.ndarray):
        pass

    source = np.empty(1, dtype=object).view(Array)
    source[0] = Signal(3)
    with pytest.deprecated_call(match="Array"):
        result = deep_unref(source)
    assert result.shape == source.shape
    assert result[0] == 3


def test_pre_06_compute_behavior_is_preserved():
    source = Signal(1)
    nested = Signal(source)
    assert nested.value == unref(nested) == 1
    assert Computed(lambda: source).value == 1
    total = computed(sum)([source])
    seen = []
    watcher = effect(seen.append)([source])
    source.value = 2
    assert nested.value == 2
    assert total.value == 2
    assert seen == [[1], [2]]
    watcher.dispose()
