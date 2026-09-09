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


def test_deep_unref_leaves_unregistered_iterables_opaque():
    class Box:
        def __init__(self, values):
            self.values = values

        def __iter__(self):
            return iter(self.values)

    nested = Signal(1)
    box = Box([nested])

    assert deep_unref(box) is box


def test_deep_unref_supports_registered_container_types():
    class Box:
        def __init__(self, values):
            self.values = values

    @deep_unref.register(Box)
    def resolve_box(box, resolve):
        return Box([resolve(value) for value in box.values])

    result = deep_unref(Box([Signal(1), {"nested": Signal(2)}]))

    assert result.values == [1, {"nested": 2}]


def test_deep_unref_cycles_reach_recursion_limit():
    cyclic = []
    cyclic.append(cyclic)

    with pytest.raises(RecursionError):
        deep_unref(cyclic)


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


def test_repeated_containers_are_resolved_independently():
    shared = [Signal(1)]
    result = deep_unref([shared, Signal(shared), shared])
    assert result == [[1], [1], [1]]
    assert len({id(item) for item in result}) == 3
    assert all(item is not shared for item in result)


@pytest.mark.parametrize("make", [lambda a, b: {a: 1, b: 2}, set, frozenset])
def test_resolved_collisions_raise(make):
    a, b = Signal("same"), Signal("same")
    value = make(a, b) if callable(make) and make not in (set, frozenset) else make([a, b])
    with pytest.raises(ValueError, match="collision"):
        deep_unref(value)


@pytest.mark.parametrize("make", [lambda a: {a: 1}, lambda a: {a}, lambda a: frozenset({a})])
def test_resolved_unhashable_members_raise(make):
    with pytest.raises(TypeError, match="unhashable"):
        deep_unref(make(Signal([])))


def test_reactive_cycle_reaches_recursion_limit():
    source = Signal(None)
    source.value = [source]
    with pytest.raises(RecursionError):
        deep_unref(source)


def test_unknown_subclasses_and_generators_are_not_consumed():
    class CustomList(list):
        def __iter__(self):
            raise AssertionError("must not iterate")

    opaque = CustomList([Signal(1)])
    assert deep_unref(opaque) is opaque
    iterator = iter([Signal(1)])
    assert deep_unref(iterator) is iterator
    assert isinstance(next(iterator), Signal)


def test_registered_handler_exception_propagates_unchanged():
    class Box:
        pass

    failure = LookupError("handler failed")

    @deep_unref.register(Box)
    def fail(value, resolve):
        raise failure

    with pytest.raises(LookupError) as caught:
        deep_unref([Box()])
    assert caught.value is failure


def test_string_key_handlers_still_resolve_keys_and_detect_collisions():
    from signified._resolve import _DeepUnref, _dict

    resolve = _DeepUnref()
    resolve.register(dict)(_dict)
    resolve.register(str)(lambda value, context: value.lower())

    assert resolve({"KEY": 1}) == {"key": 1}
    with pytest.raises(ValueError, match="collision"):
        resolve({"KEY": 1, "key": 2})


def test_dictionary_resolves_repeated_values_independently_and_recurses_on_cycles():
    shared = [Signal(1)]
    resolved = deep_unref({"first": shared, "second": shared})
    assert resolved == {"first": [1], "second": [1]}
    assert resolved["first"] is not resolved["second"]
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(RecursionError):
        deep_unref(cyclic)


def test_registration_during_traversal_only_affects_subsequent_calls():
    from signified._resolve import _DeepUnref, _list

    resolve = _DeepUnref()
    resolve.register(list)(_list)

    class Register:
        pass

    @resolve.register(Register)
    def register_scalar(value, context):
        resolve.register(int)(lambda value, context: value + 10)
        return context(1)

    assert resolve([Register(), Signal(1), 1]) == [1, 1, 1]
    assert resolve([Signal(1), 1]) == [11, 11]


def test_repeated_signal_reads_observe_mutation_during_traversal():
    from signified._resolve import _DeepUnref, _list

    resolve = _DeepUnref()
    resolve.register(list)(_list)
    source = Signal(1)

    class Mutate:
        pass

    @resolve.register(Mutate)
    def mutate(value, context):
        source.value = 2
        return None

    assert resolve([source, Mutate(), source]) == [1, None, 2]
    assert resolve(source) == 2


def test_custom_handler_cycles_reach_recursion_limit():
    from signified._resolve import _DeepUnref, _dict, _list

    resolve = _DeepUnref()
    resolve.register(dict)(_dict)
    resolve.register(list)(_list)

    class Box:
        pass

    @resolve.register(Box)
    def resolve_box(value, context):
        return context(value)

    with pytest.raises(RecursionError):
        resolve({"box": [Box()]})


def test_scalar_signal_subclasses_still_use_their_value_property():
    class CountingSignal(Signal):
        reads = 0

        @property
        def value(self):
            self.reads += 1
            return super().value

    source = CountingSignal(1)
    assert deep_unref([source, source]) == [1, 1]
    assert source.reads == 2


def test_numpy_preserves_shape_dtype_and_resolves_repeated_objects_independently():
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
    assert result[0] is not result[1]
    assert result[0] == result[1] == [1, 2]
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
