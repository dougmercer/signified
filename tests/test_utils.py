from signified import Computed, Signal, as_signal, has_value, reactive_method, unref


def test_has_value():
    """Test the has_value type guard function."""
    s = Signal(5)
    c = Computed(lambda: 10)

    assert has_value(s, int)
    assert has_value(c, int)
    assert has_value(15, int)
    assert not has_value(s, str)


def test_unref_nested_signals():
    """Test unref function with deeply nested Signals."""
    s = Signal(Signal(Signal(Signal(5))))
    assert unref(s) == 5


def test_reactive_method_decorator():
    """Test the reactive_method decorator."""

    class MyClass:
        def __init__(self):
            self.x = Signal(5)
            self.y = Signal(10)

        @reactive_method("x", "y")
        def sum(self):
            return self.x.value + self.y.value

    obj = MyClass()
    result = obj.sum()

    assert result.value == 15
    obj.x.value = 7
    assert result.value == 17


def test_as_signal():
    """Test the as_signal function."""
    s1 = as_signal(5)
    s2 = as_signal(Signal(10))

    assert isinstance(s1, Signal)
    assert isinstance(s2, Signal)
    assert s1.value == 5
    assert s2.value == 10
