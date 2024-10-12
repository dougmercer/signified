import sys
from typing import TypeVar, Union

from signified import Signal, Computed, computed, unref

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type

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
