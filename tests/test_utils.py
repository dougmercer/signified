from signified import Signal, Computed, has_value, unref, reactive_method, as_signal


def test_has_value() -> None:
    """Test the has_value type guard function."""
    s = Signal(5)
    c = Computed(lambda: 10)

    assert has_value(s, int)
    assert has_value(c, int)
    assert has_value(15, int)
    assert not has_value(s, str)


def test_unref_nested_signals() -> None:
    """Test unref function with deeply nested Signals."""
    s = Signal(Signal(Signal(Signal(5))))
    assert unref(s) == 5


def test_reactive_method_decorator() -> None:
    """Test the reactive_method decorator."""

    class MyClass:
        def __init__(self) -> None:
            self.x = Signal(5)
            self.y = Signal(10)

        @reactive_method("x", "y")
        def sum(self) -> int:
            return self.x.value + self.y.value

    obj = MyClass()
    result = obj.sum()

    assert result.value == 15
    obj.x.value = 7
    assert result.value == 17


def test_as_signal() -> None:
    """Test the as_signal function."""
    s1 = as_signal(5)
    s2 = as_signal(Signal(10))

    assert isinstance(s1, Signal)
    assert isinstance(s2, Signal)
    assert s1.value == 5
    assert s2.value == 10
