from math import floor
from typing import TypeVar, Union, assert_type

from signified import Computed, Signal, computed, reactive_method, unref

T = TypeVar("T")

Numeric = Union[int, float]


def test_signal_types():
    a = Signal(1)
    assert_type(a, Signal[int])
    assert_type(a.value, int)

    b = Signal(a)
    assert_type(b, Signal[int])
    assert_type(b.value, int)

    c = Signal(b)
    assert_type(c, Signal[int])
    assert_type(c.value, int)

    d = Signal(Signal(Signal(Signal(Signal(1.2)))))
    assert_type(d, Signal[float])
    assert_type(d.value, float)


def test_computed_types():
    def blah() -> float:
        return 1.1

    def bloo() -> int:
        return 1

    e = Computed(blah)
    assert_type(e, Computed[float])
    assert_type(e.value, float)

    f = Computed(bloo)
    assert_type(f, Computed[int])
    assert_type(f.value, int)


def test_arithmetic_types():
    a = Signal(1)
    b = Signal(2)
    c = Signal(3.0)

    result = a + b
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    result = a + c
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_reverse_arithmetic_types():
    a = Signal(10)
    b = Signal(2.0)

    result = 15 - a
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    result = 15 - b
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_round_floor_divmod_types():
    a = Signal(10)
    b = Signal(3.14159)

    result = round(a)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    result = round(b, 2)
    assert_type(result, Computed[float])
    assert_type(unref(result), float)

    result = floor(b)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    result = divmod(a, 3)
    assert_type(result, Computed[tuple[float, float]])
    assert_type(unref(result), tuple[float, float])

    result = divmod(10, a)
    assert_type(result, Computed[tuple[float, float]])
    assert_type(unref(result), tuple[float, float])


def test_comparison_types():
    a = Signal(1)
    b = Signal(Signal(Signal(2)))

    result = a > b
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_where_types():
    a = Signal(1)
    b = Signal(2.0)
    condition = Signal(True)

    result = condition.where(a, b)
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_unref_types():
    a = Signal(1)
    b = Signal(Signal(2.0))
    c = Computed(lambda: "three")

    assert_type(unref(a), int)
    assert_type(unref(b), float)
    assert_type(unref(c), str)


def test_complex_expression_types():
    a = Signal(1)
    b = Signal(2.0)
    c = Computed(lambda: 3)

    result = (a + b) * c
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_call_inference():
    class Person:
        def __init__(self, name: str):
            self.name = name

        def __call__(self, formal=False) -> str:
            return f"{'Greetings' if formal else 'Hi'}, I'm {self.name}!"

    a = computed(lambda: Person("Doug"))()

    assert_type(a, Computed[Person])
    assert_type(a(), Computed[str])


def test_reactive_method_inference():
    class Counter:
        def __init__(self) -> None:
            self.value = Signal(1)

        @reactive_method("value")
        def plus(self, delta: int) -> int:
            return self.value.value + delta

    counter = Counter()
    result = counter.plus(2)

    assert_type(result, Computed[int])
    assert_type(unref(result), int)
