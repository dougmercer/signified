import gc
import weakref

import pytest

from signified import Binding, Computed, Signal, deep_unref, unref


def test_signal_basic():
    """Test basic Signal functionality."""
    s = Signal(5)
    assert s.value == 5

    s.value = 10
    assert s.value == 10


def test_signal_can_store_reactive_initial_value():
    inner = Signal(5)
    outer = Signal(inner)

    assert outer.value is inner


def test_stored_reactive_value_does_not_create_containment_dependency():
    inner = Signal(1)
    outer = Signal(inner)
    runs = 0

    def read_outer():
        nonlocal runs
        runs += 1
        return outer.value

    derived = Computed(read_outer)
    assert derived.value is inner
    assert runs == 1

    inner.value = 2
    assert derived.value is inner
    assert runs == 1


def test_signal_can_be_assigned_a_reactive_value():
    inner = Computed(lambda: 10)
    outer: Signal[object] = Signal(5)

    outer.value = inner

    assert outer.value is inner


def test_signal_reactive_assignment_uses_identity_for_change_detection():
    first = Signal(1)
    second = Signal(1)
    outer = Signal(first)
    derived = Computed(lambda: outer.value)

    assert derived.value is first
    outer.value = second
    assert derived.value is second


def test_signal_container_is_opaque_to_reactive_children():
    child = Signal(1)
    outer = Signal([child])
    runs = 0

    def read_outer():
        nonlocal runs
        runs += 1
        return outer.value

    derived = Computed(read_outer)
    assert derived.value == [child]
    assert runs == 1

    child.value = 2
    assert derived.value == [child]
    assert runs == 1
    assert deep_unref(outer) == [2]


def test_unref_is_shallow_and_deep_unref_is_recursive():
    inner = Signal(1)
    outer = Signal(inner)

    assert unref(outer) is inner
    assert deep_unref(outer) == 1


def test_unref():
    """Test the unref function."""
    s = Signal(5)
    c = Computed(lambda: s.value * 2)

    assert unref(s) == 5
    assert unref(c) == 10
    assert unref(15) == 15


def test_signal_observer():
    """Test Signal observer pattern."""
    s = Signal(5)

    class Appender:
        """An observer that appends values whenever a signal changes."""

        def __init__(self, s: Signal):
            self.s = s
            self.values = []

        def update(self):
            self.values.append(self.s.value)

    appender = Appender(s)
    s.subscribe(appender)

    s.value = 10
    s.value = 15

    assert appender.values == [10, 15]


def test_signal_unsubscribe_stops_notifications():
    s = Signal(5)

    class Appender:
        def __init__(self, signal: Signal):
            self.signal = signal
            self.values: list[int] = []

        def update(self) -> None:
            self.values.append(self.signal.value)

    appender = Appender(s)
    s.subscribe(appender)
    s.unsubscribe(appender)

    s.value = 10
    assert appender.values == []


def test_signal_drops_garbage_collected_observers():
    s = Signal(5)

    class Appender:
        def update(self) -> None:
            raise AssertionError("dead observer should never be notified")

    appender = Appender()
    observer_ref = weakref.ref(appender)
    s.subscribe(appender)

    del appender
    gc.collect()

    assert observer_ref() is None
    assert not s._observers


def test_signal_context_manager():
    """Test the Signal's context manager functionality."""
    s = Signal(5)
    t = Binding(s)

    with s.at(10):
        assert s.value == 10
        assert t.value == 10

    assert s.value == 5
    assert t.value == 5


def test_binding_context_manager_restores_source():
    inner = Signal(5)
    outer = Binding(inner)

    with outer.at(10):
        assert outer.value == 10

    assert outer.source is inner
    inner.value = 20
    assert outer.value == 20


def test_with_name_sets_display_name():
    s = Signal(1).with_name("counter")
    assert f"{s:n}" == "counter"


def test_equal_distinct_containers_replace_and_invalidate():
    from signified import Effect

    for old, new in [([1], [1]), ({"a": 1}, {"a": 1})]:
        source = Signal(old)
        derived = Computed(lambda: source.value)
        seen = []
        watcher = Effect(lambda: seen.append(derived.value))
        source.value = new
        assert source.value is new
        assert derived.value is new
        assert len(seen) == 2
        assert seen[0] is old and seen[1] is new
        watcher.dispose()


def test_identity_equality_does_not_call_user_equality():
    class Value:
        def __eq__(self, other):
            raise AssertionError("must not compare")

    value = Value()
    source = Signal(value)
    version = source._version
    source.value = value
    assert source._version == version
    replacement = Value()
    source.value = replacement
    assert source.value is replacement


def test_scalar_equality_retains_previous_value_and_distinguishes_types():
    from signified import Effect

    nan = float("nan")
    source = Signal(nan)
    seen = []
    watcher = Effect(lambda: seen.append(source.value))
    source.value = float("nan")
    assert source.value is nan
    assert len(seen) == 1
    source.value = 1
    source.value = True
    assert source.value is True
    assert len(seen) == 3
    watcher.dispose()


def test_binding_follows_one_boundary_even_when_result_is_reactive():
    inner = Signal(1)
    outer = Signal(inner)
    binding = Binding(outer)
    assert binding.value is inner
    assert unref(binding) is inner
    replacement = Signal(2)
    outer.value = replacement
    assert binding.value is replacement


class _Box:
    def __init__(self) -> None:
        self.count = 0


def test_signal_forwards_attribute_writes_to_the_wrapped_object_and_notifies():
    box = _Box()
    signal = Signal(box)
    count = signal.count
    assert count.value == 0

    signal.count = 1  # type: ignore[attr-defined]

    assert box.count == 1
    assert count.value == 1


def test_signal_unknown_attribute_write_raises_instead_of_shadowing():
    box = _Box()
    signal = Signal(box)

    with pytest.raises(AttributeError, match="cuont"):
        signal.cuont = 1  # type: ignore[attr-defined]
    assert not hasattr(box, "cuont")
    assert isinstance(signal.count, Computed)  # proxying is intact


def test_computed_and_binding_do_not_forward_attribute_writes():
    box = _Box()
    signal = Signal(box)
    passthrough = Computed(lambda: signal.value)
    binding = Binding(signal)

    with pytest.raises(AttributeError):
        passthrough.count = 1  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        binding.count = 1  # type: ignore[attr-defined]
    assert box.count == 0


def test_signal_item_assignment_mutates_and_notifies():
    numbers = Signal([1, 2, 3])
    total = Computed(lambda: sum(numbers.value))
    assert total.value == 6

    numbers[1] = 10

    assert numbers.value == [1, 10, 3]
    assert total.value == 14


def test_computed_and_binding_do_not_forward_item_assignment():
    numbers = Signal([1, 2, 3])
    passthrough = Computed(lambda: numbers.value)
    binding = Binding(numbers)

    with pytest.raises(TypeError):
        passthrough[0] = 9  # type: ignore[index]
    with pytest.raises(TypeError):
        binding[0] = 9  # type: ignore[index]
    assert numbers.value == [1, 2, 3]


def test_signal_forwards_item_deletion_and_notifies():
    numbers = Signal([1, 2, 3])
    total = Computed(lambda: sum(numbers.value))
    assert total.value == 6

    del numbers[1]

    assert numbers.value == [1, 3]
    assert total.value == 4


def test_signal_forwards_key_deletion_for_dicts():
    mapping = Signal({"a": 1, "b": 2})
    keys = Computed(lambda: sorted(mapping.value))
    assert keys.value == ["a", "b"]

    del mapping["a"]

    assert mapping.value == {"b": 2}
    assert keys.value == ["b"]


def test_item_deletion_rejects_unsupported_containers():
    text = Signal("abc")

    with pytest.raises(TypeError, match="does not support item deletion"):
        del text[0]  # type: ignore[attr-defined]

    assert text.value == "abc"


def test_computed_and_binding_do_not_forward_item_deletion():
    numbers = Signal([1, 2, 3])
    passthrough = Computed(lambda: numbers.value)
    binding = Binding(numbers)

    with pytest.raises(TypeError):
        del passthrough[0]  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        del binding[0]  # type: ignore[attr-defined]
    assert numbers.value == [1, 2, 3]


def test_item_deletion_notifies_once():
    """`__delitem__` mutates in place, so notification is unconditional."""
    numbers = Signal([1, 2, 3])
    seen: list[list[int]] = []
    effect = numbers.rx.effect(lambda value: seen.append(list(value)))

    del numbers[2]

    assert seen == [[1, 2, 3], [1, 2]]
    effect.dispose()
