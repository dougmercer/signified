from signified import Computed, Signal, unref


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
    c = Computed(lambda: s.value * 2, dependencies=[s])

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


def test_signal_context_manager():
    """Test the Signal's context manager functionality."""
    s = Signal(5)
    t = Signal(s)

    with s.at(10):
        assert s.value == 10
        assert t.value == 10

    assert s.value == 5
    assert t.value == 5
