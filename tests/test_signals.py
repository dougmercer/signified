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


def test_signal_rejects_reactive_initial_value():
    with pytest.raises(TypeError, match="use Binding"):
        Signal(Signal(5))


def test_signal_rejects_reactive_assignment():
    outer = Signal(5)
    with pytest.raises(TypeError, match="use Binding"):
        outer.value = Signal(10)  # type: ignore[assignment]
    assert outer.value == 5


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
