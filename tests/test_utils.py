import pytest

from signified import Computed, Signal, as_signal, computed, has_value, reactive_method, unref
from signified.core import _coerce_to_bool, _has_changed


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
    with pytest.warns(DeprecationWarning, match=r"reactive_method\(\.\.\.\)"):

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


def test_reactive_method_dep_names_are_deprecated_and_ignored():
    with pytest.warns(DeprecationWarning, match=r"reactive_method\(\.\.\.\)"):

        class MyClass:
            def __init__(self):
                self.x = Signal(2)
                self.y = Signal(3)

            @reactive_method("nonexistent", "still_unused")
            def sum(self):
                return self.x.value + self.y.value

    obj = MyClass()
    result = obj.sum()

    assert result.value == 5
    obj.x.value = 10
    assert result.value == 13


def test_reactive_method_without_dep_names_still_warns():
    with pytest.warns(DeprecationWarning, match=r"reactive_method\(\.\.\.\)"):

        class MyClass:
            def __init__(self):
                self.x = Signal(4)

            @reactive_method()
            def doubled(self):
                return self.x.value * 2

    obj = MyClass()
    result = obj.doubled()

    assert result.value == 8
    obj.x.value = 6
    assert result.value == 12


def test_computed_decorator_on_method_tracks_instance_state():
    class Counter:
        def __init__(self):
            self.value = Signal(2)

        @computed
        def doubled(self):
            return self.value.value * 2

    counter = Counter()
    result = counter.doubled()

    assert result.value == 4
    counter.value.value = 7
    assert result.value == 14


def test_computed_decorator_on_method_tracks_reactive_arguments():
    class Counter:
        def __init__(self):
            self.value = Signal(1)

        @computed
        def plus(self, delta):
            return self.value.value + delta

    counter = Counter()
    delta = Signal(3)
    result = counter.plus(delta)

    assert result.value == 4
    delta.value = 10
    assert result.value == 11
    counter.value.value = 5
    assert result.value == 15


def test_as_signal():
    """Test the as_signal function."""
    s1 = as_signal(5)
    s2 = as_signal(Signal(10))

    assert isinstance(s1, Signal)
    assert isinstance(s2, Signal)
    assert s1.value == 5
    assert s2.value == 10


def test_has_changed_treats_nan_as_unchanged():
    nan = float("nan")
    assert _has_changed(nan, nan) is False


def test_has_changed_with_broken_eq_is_treated_as_changed():
    class BrokenEq:
        def __eq__(self, other):  # pragma: no cover - explicit error path
            raise RuntimeError("eq failed")

    assert _has_changed(BrokenEq(), BrokenEq()) is True


def test_has_changed_with_ambiguous_equality_all_true_is_unchanged():
    class AmbiguousEqResult:
        def __bool__(self):
            raise ValueError("ambiguous truth value")

        def all(self):
            return True

    class WithAmbiguousEq:
        def __eq__(self, other):  # type: ignore
            return AmbiguousEqResult()

    assert _has_changed(object(), WithAmbiguousEq()) is False


def test_coerce_to_bool_handles_ambiguous_bool_with_all_fallback():
    class AmbiguousBool:
        def __bool__(self):
            raise ValueError("ambiguous truth value")

        def all(self):
            return True

    assert _coerce_to_bool(AmbiguousBool()) is True


def test_coerce_to_bool_uses_all_fallback():
    class AmbiguousBool:
        def __bool__(self):
            raise ValueError("ambiguous truth value")

        def all(self):
            return False

    assert _coerce_to_bool(AmbiguousBool()) is False
