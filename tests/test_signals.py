import gc
import weakref

from signified import Computed, Signal, batch, unref


def test_signal_basic():
    """Test basic Signal functionality."""
    s = Signal(5)
    assert s.value == 5

    s.value = 10
    assert s.value == 10


def test_signal_nested():
    """Test nested Signal functionality."""
    s1 = Signal(5)
    s2 = Signal(s1)
    s3 = Signal(s2)

    assert s3.value == 5

    s1.value = 10
    assert s3.value == 10


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
    t = Signal(s)

    with s.at(10):
        assert s.value == 10
        assert t.value == 10

    assert s.value == 5
    assert t.value == 5


def test_with_name_sets_display_name():
    s = Signal(1).with_name("counter")
    assert f"{s:n}" == "counter"


def test_batch_defers_non_reactive_observer_updates_until_exit():
    s = Signal(0)

    class Appender:
        def __init__(self, source: Signal[int]) -> None:
            self.source = source
            self.values: list[int] = []

        def update(self) -> None:
            self.values.append(self.source.value)

    appender = Appender(s)
    s.subscribe(appender)

    with batch():
        s.value = 1
        s.value = 2
        assert appender.values == []

    assert appender.values == [2]


def test_batch_keeps_computed_reads_current_inside_batch():
    left = Signal(1)
    right = Signal(2)
    total = left + right

    with batch():
        left.value = 10
        assert total.value == 12
        right.value = 20
        assert total.value == 30


def test_nested_batches_only_flush_on_outer_exit():
    s = Signal(0)

    class Appender:
        def __init__(self, source: Signal[int]) -> None:
            self.source = source
            self.values: list[int] = []

        def update(self) -> None:
            self.values.append(self.source.value)

    appender = Appender(s)
    s.subscribe(appender)

    with batch():
        s.value = 1
        with batch():
            s.value = 2
        assert appender.values == []
        s.value = 3
        assert appender.values == []

    assert appender.values == [3]
