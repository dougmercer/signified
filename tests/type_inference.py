from math import ceil, floor, trunc
from typing import Any, TypeVar, Union, assert_type

from signified import Computed, Signal, computed, reactive_method, unref

T = TypeVar("T")
Numeric = Union[int, float]


def test_signal_init():
    a = Signal(1)
    assert_type(a, Signal[int])
    assert_type(a.value, int)

    b = Signal(a)
    assert_type(b, Signal[int])
    assert_type(b.value, int)

    c = Signal(Signal(Signal(Signal(Signal(1.2)))))
    assert_type(c, Signal[float])
    assert_type(c.value, float)


def test_computed_init():
    c_int = Computed(lambda: 1)
    assert_type(c_int, Computed[int])
    assert_type(c_int.value, int)

    c_float = Computed(lambda: 1.1)
    assert_type(c_float, Computed[float])
    assert_type(c_float.value, float)


def test_getattr():
    class Person:
        def __init__(self, name: str):
            self.name = name

    person = Signal(Person("Alice"))
    name = person.name
    assert_type(name, Computed[Any])


def test_call():
    class Person:
        def __init__(self, name: str):
            self.name = name

        def __call__(self, formal: bool = False) -> str:
            return f"{'Greetings' if formal else 'Hi'}, I'm {self.name}!"

    person = computed(lambda: Person("Doug"))()
    assert_type(person, Computed[Person])
    assert_type(person(), Computed[str])
    assert_type(person(formal=True), Computed[str])


def test_abs():
    abs_int = abs(Signal(-5))
    assert_type(abs_int, Computed[int])
    assert_type(unref(abs_int), int)

    abs_bool = abs(Signal(True))
    assert_type(abs_bool, Computed[int])
    assert_type(unref(abs_bool), int)

    abs_complex = abs(Signal(1 + 2j))
    assert_type(abs_complex, Computed[float])
    assert_type(unref(abs_complex), float)


def test_as_bool():
    result = Signal(1).as_bool()
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_rx_map():
    result = Signal(2).rx.map(lambda x: x * 2)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_rx_tap():
    result = Signal(2).rx.tap(lambda x: x + 1)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_rx_len():
    result = Signal([1, 2, 3]).rx.len()
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_rx_is():
    result = Signal(10).rx.is_(10)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_rx_is_not():
    result = Signal(10).rx.is_not(None)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_rx_eq():
    result = Signal(10).rx.eq(10)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_rx_in():
    result = Signal("a").rx.in_("cat")
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_str():
    result = str(Signal(1))
    assert_type(result, str)


def test_round():
    rounded_int = round(Signal(10))
    assert_type(rounded_int, Computed[int])
    assert_type(unref(rounded_int), int)

    rounded_bool = round(Signal(True))
    assert_type(rounded_bool, Computed[int])
    assert_type(unref(rounded_bool), int)

    rounded_bool_with_ndigits = round(Signal(True), 2)
    assert_type(rounded_bool_with_ndigits, Computed[int])
    assert_type(unref(rounded_bool_with_ndigits), int)

    rounded_int_with_ndigits = round(Signal(10), 2)
    assert_type(rounded_int_with_ndigits, Computed[int])
    assert_type(unref(rounded_int_with_ndigits), int)

    rounded_float = round(Signal(3.14159), 2)
    assert_type(rounded_float, Computed[float])
    assert_type(unref(rounded_float), float)

    rounded_float_default = round(Signal(3.14159))
    assert_type(rounded_float_default, Computed[int])
    assert_type(unref(rounded_float_default), int)


def test_ceil():
    result = ceil(Signal(3.14))
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_floor():
    result = floor(Signal(3.14))
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_invert():
    result = ~Signal(5)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    bool_result = ~Signal(True)
    assert_type(bool_result, Computed[int])
    assert_type(unref(bool_result), int)


def test_neg():
    result = -Signal(5)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    bool_result = -Signal(True)
    assert_type(bool_result, Computed[int])
    assert_type(unref(bool_result), int)


def test_pos():
    result = +Signal(-5)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    bool_result = +Signal(True)
    assert_type(bool_result, Computed[int])
    assert_type(unref(bool_result), int)


def test_trunc():
    result = trunc(Signal(3))
    assert_type(result, Computed[int])
    assert_type(unref(result), int)

    bool_result = trunc(Signal(True))
    assert_type(bool_result, Computed[int])
    assert_type(unref(bool_result), int)

    float_result = trunc(Signal(3.14))
    assert_type(float_result, Computed[int])
    assert_type(unref(float_result), int)


def test_add():
    int_sum = Signal(1) + Signal(2)
    assert_type(int_sum, Computed[int])
    assert_type(unref(int_sum), int)

    numeric_sum = Signal(1) + Signal(2.0)
    assert_type(numeric_sum, Computed[float])
    assert_type(unref(numeric_sum), float)

    numeric_sum_reverse_order = Signal(3.0) + Signal(2)
    assert_type(numeric_sum_reverse_order, Computed[float])
    assert_type(unref(numeric_sum_reverse_order), float)

    str_sum = Signal("a") + Signal("b")
    assert_type(str_sum, Computed[str])
    assert_type(unref(str_sum), str)

    list_sum = Signal([1, 2]) + Signal([3])
    assert_type(list_sum, Computed[list[int]])
    assert_type(unref(list_sum), list[int])

    class Vec:
        def __add__(self, other: int) -> "Vec":
            return self

    vec_sum = Signal(Vec()) + 1
    assert_type(vec_sum, Computed[Vec])


def test_and():
    int_and = Signal(7) & Signal(3)
    assert_type(int_and, Computed[int])
    assert_type(unref(int_and), int)

    bool_and = Signal(True) & Signal(False)
    assert_type(bool_and, Computed[bool])
    assert_type(unref(bool_and), bool)


def test_contains():
    result = Signal([1, 2, 3]).contains(2)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)

    text_contains = Signal("abc").contains("b")
    assert_type(text_contains, Computed[bool])
    assert_type(unref(text_contains), bool)


def test_divmod():
    int_divmod = divmod(Signal(10), 3)
    assert_type(int_divmod, Computed[tuple[int, int]])
    assert_type(unref(int_divmod), tuple[int, int])

    bool_divmod = divmod(Signal(True), 2)
    assert_type(bool_divmod, Computed[tuple[int, int]])
    assert_type(unref(bool_divmod), tuple[int, int])

    float_divmod = divmod(Signal(10.0), 3)
    assert_type(float_divmod, Computed[tuple[float, float]])
    assert_type(unref(float_divmod), tuple[float, float])

    float_divmod_float = divmod(Signal(10.0), 3.0)
    assert_type(float_divmod_float, Computed[tuple[float, float]])
    assert_type(unref(float_divmod_float), tuple[float, float])


def test_is_not():
    result = Signal(10).is_not(None)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_eq():
    result = Signal(10).eq(10)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_floordiv():
    int_div = Signal(10) // Signal(3)
    assert_type(int_div, Computed[int])
    assert_type(unref(int_div), int)

    bool_div = Signal(True) // Signal(2)
    assert_type(bool_div, Computed[int])
    assert_type(unref(bool_div), int)

    numeric_div = Signal(10) // Signal(2.0)
    assert_type(numeric_div, Computed[Numeric])
    assert_type(unref(numeric_div), Numeric)

    float_div = Signal(10.0) // Signal(2)
    assert_type(float_div, Computed[Numeric])
    assert_type(unref(float_div), Numeric)


def test_ge():
    result = Signal(10) >= Signal(5)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_gt():
    result = Signal(10) > Signal(5)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_le():
    result = Signal(5) <= Signal(5)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_lt():
    result = Signal(5) < Signal(10)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_lshift():
    shifted = Signal(8) << Signal(2)
    assert_type(shifted, Computed[int])
    assert_type(unref(shifted), int)


def test_matmul():
    class Matrix:
        def __matmul__(self, other: int) -> int:
            return other + 1

    result = Signal(Matrix()) @ 2
    assert_type(result, Computed[Matrix | int])


def test_mod():
    modded = Signal(17) % Signal(5)
    assert_type(modded, Computed[int])
    assert_type(unref(modded), int)

    bool_modded = Signal(True) % Signal(2)
    assert_type(bool_modded, Computed[int])
    assert_type(unref(bool_modded), int)

    float_modded = Signal(17.0) % Signal(5)
    assert_type(float_modded, Computed[Numeric])
    assert_type(unref(float_modded), Numeric)


def test_mul():
    int_product = Signal(4) * 3
    assert_type(int_product, Computed[int])
    assert_type(unref(int_product), int)

    str_repeat = Signal("a") * 3
    assert_type(str_repeat, Computed[str])
    assert_type(unref(str_repeat), str)

    list_repeat = Signal([1, 2]) * 3
    assert_type(list_repeat, Computed[list[int]])
    assert_type(unref(list_repeat), list[int])

    numeric_product = Signal(4) * Signal(2.5)
    assert_type(numeric_product, Computed[Numeric])
    assert_type(unref(numeric_product), Numeric)


def test_ne():
    result = Signal(5) != Signal(6)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_or():
    int_or = Signal(7) | Signal(3)
    assert_type(int_or, Computed[int])
    assert_type(unref(int_or), int)

    bool_or = Signal(True) | Signal(False)
    assert_type(bool_or, Computed[bool])
    assert_type(unref(bool_or), bool)


def test_rshift():
    shifted = Signal(32) >> Signal(2)
    assert_type(shifted, Computed[int])
    assert_type(unref(shifted), int)


def test_pow():
    powered = Signal(2) ** Signal(3)
    assert_type(powered, Computed[int])
    assert_type(unref(powered), int)

    bool_powered = Signal(True) ** Signal(2)
    assert_type(bool_powered, Computed[int])
    assert_type(unref(bool_powered), int)

    float_powered = Signal(2.0) ** Signal(3)
    assert_type(float_powered, Computed[Numeric])
    assert_type(unref(float_powered), Numeric)


def test_sub():
    int_difference = Signal(10) - Signal(3)
    assert_type(int_difference, Computed[int])
    assert_type(unref(int_difference), int)

    numeric_difference = Signal(10) - Signal(2.0)
    assert_type(numeric_difference, Computed[Numeric])
    assert_type(unref(numeric_difference), Numeric)


def test_truediv():
    int_div = Signal(7) / Signal(3)
    assert_type(int_div, Computed[float])
    assert_type(unref(int_div), float)

    bool_div = Signal(True) / Signal(2)
    assert_type(bool_div, Computed[float])
    assert_type(unref(bool_div), float)

    float_div = Signal(7) / Signal(2.0)
    assert_type(float_div, Computed[float])
    assert_type(unref(float_div), float)

    float_float_div = Signal(7.0) / Signal(2.0)
    assert_type(float_float_div, Computed[float])
    assert_type(unref(float_float_div), float)


def test_xor():
    int_xor = Signal(7) ^ Signal(3)
    assert_type(int_xor, Computed[int])
    assert_type(unref(int_xor), int)

    bool_xor = Signal(True) ^ Signal(False)
    assert_type(bool_xor, Computed[bool])
    assert_type(unref(bool_xor), bool)


def test_radd():
    int_sum = 5 + Signal(2)
    assert_type(int_sum, Computed[int])
    assert_type(unref(int_sum), int)

    numeric_sum = 5 + Signal(2.0)
    assert_type(numeric_sum, Computed[float])
    assert_type(unref(numeric_sum), float)

    reverse_numeric_sum = 5.0 + Signal(2)
    assert_type(reverse_numeric_sum, Computed[float])
    assert_type(unref(reverse_numeric_sum), float)


def test_rand():
    int_and = 7 & Signal(3)
    assert_type(int_and, Computed[int])
    assert_type(unref(int_and), int)

    bool_and = True & Signal(False)
    assert_type(bool_and, Computed[bool])
    assert_type(unref(bool_and), bool)


def test_rdivmod():
    int_divmod = divmod(10, Signal(3))
    assert_type(int_divmod, Computed[tuple[int, int]])
    assert_type(unref(int_divmod), tuple[int, int])

    bool_divmod = divmod(2, Signal(True))
    assert_type(bool_divmod, Computed[tuple[int, int]])
    assert_type(unref(bool_divmod), tuple[int, int])

    float_divmod = divmod(10.0, Signal(3.0))
    assert_type(float_divmod, Computed[tuple[float, float]])
    assert_type(unref(float_divmod), tuple[float, float])

    int_float_divmod = divmod(10, Signal(3.0))
    assert_type(int_float_divmod, Computed[tuple[float, float]])
    assert_type(unref(int_float_divmod), tuple[float, float])


def test_rfloordiv():
    int_div = 10 // Signal(3)
    assert_type(int_div, Computed[int])
    assert_type(unref(int_div), int)

    bool_div = 2 // Signal(True)
    assert_type(bool_div, Computed[int])
    assert_type(unref(bool_div), int)

    numeric_div = 10 // Signal(2.0)
    assert_type(numeric_div, Computed[Numeric])
    assert_type(unref(numeric_div), Numeric)


def test_rmod():
    modded = 10 % Signal(3)
    assert_type(modded, Computed[int])
    assert_type(unref(modded), int)

    bool_modded = 2 % Signal(True)
    assert_type(bool_modded, Computed[int])
    assert_type(unref(bool_modded), int)


def test_rmul():
    int_product = 3 * Signal(4)
    assert_type(int_product, Computed[int])
    assert_type(unref(int_product), int)

    str_repeat = 3 * Signal("a")
    assert_type(str_repeat, Computed[str])
    assert_type(unref(str_repeat), str)

    list_repeat = 3 * Signal([1, 2])
    assert_type(list_repeat, Computed[list[int]])
    assert_type(unref(list_repeat), list[int])

    numeric_product = 3 * Signal(2.5)
    assert_type(numeric_product, Computed[Numeric])
    assert_type(unref(numeric_product), Numeric)


def test_ror():
    int_or = 7 | Signal(3)
    assert_type(int_or, Computed[int])
    assert_type(unref(int_or), int)

    bool_or = True | Signal(False)
    assert_type(bool_or, Computed[bool])
    assert_type(unref(bool_or), bool)


def test_rpow():
    powered = 3 ** Signal(2)
    assert_type(powered, Computed[int])
    assert_type(unref(powered), int)

    bool_powered = 2 ** Signal(True)
    assert_type(bool_powered, Computed[int])
    assert_type(unref(bool_powered), int)

    float_powered = 3.0 ** Signal(2)
    assert_type(float_powered, Computed[Numeric])
    assert_type(unref(float_powered), Numeric)


def test_rsub():
    int_difference = 15 - Signal(10)
    assert_type(int_difference, Computed[int])
    assert_type(unref(int_difference), int)

    numeric_difference = 15 - Signal(2.0)
    assert_type(numeric_difference, Computed[Numeric])
    assert_type(unref(numeric_difference), Numeric)


def test_rtruediv():
    int_div = 7 / Signal(2)
    assert_type(int_div, Computed[float])
    assert_type(unref(int_div), float)

    bool_div = 2 / Signal(True)
    assert_type(bool_div, Computed[float])
    assert_type(unref(bool_div), float)

    float_div = 7 / Signal(2.0)
    assert_type(float_div, Computed[float])
    assert_type(unref(float_div), float)

    float_float_div = 7.0 / Signal(2.0)
    assert_type(float_float_div, Computed[float])
    assert_type(unref(float_float_div), float)


def test_rxor():
    int_xor = 7 ^ Signal(3)
    assert_type(int_xor, Computed[int])
    assert_type(unref(int_xor), int)

    bool_xor = True ^ Signal(False)
    assert_type(bool_xor, Computed[bool])
    assert_type(unref(bool_xor), bool)


def test_getitem():
    numbers = Signal([1, 2, 3])
    assert_type(numbers[1], Computed[int])
    assert_type(numbers[Signal(1)], Computed[int])
    assert_type(numbers[1:], Computed[list[int]])
    assert_type(numbers[-1], Computed[int])

    tuple_source = tuple(range(1, 4))
    tuple_values = Signal(tuple_source)
    assert_type(tuple_values[1], Computed[int])
    assert_type(tuple_values[1:], Computed[tuple[int, ...]])
    assert_type(tuple_values[-1], Computed[int])

    mapping = Signal({"a": 1})
    assert_type(mapping["a"], Computed[int])
    assert_type(mapping[Signal("a")], Computed[int])

    chars = Signal("abc")
    assert_type(chars[0], Computed[str])
    assert_type(chars[Signal(0)], Computed[str])
    assert_type(chars[1:], Computed[str])

    class Bag:
        def __getitem__(self, key: str) -> int:
            return 1

    bag = Signal(Bag())
    assert_type(bag["x"], Computed[int])


def test_setattr():
    class Person:
        def __init__(self, name: str):
            self.name = name

    person = Signal(Person("Alice"))
    result = person.__setattr__("name", "Bob")
    assert_type(result, None)


def test_setitem():
    values = Signal([1, 2, 3])
    result = values.__setitem__(1, 4)
    assert_type(result, None)

    mapping = Signal({"a": 1})
    map_result = mapping.__setitem__("a", 2)
    assert_type(map_result, None)


def test_where():
    a = Signal(1)
    b = Signal(2.0)
    condition = Signal(True)

    result = condition.where(a, b)
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_unref():
    a = Signal(1)
    b = Signal(Signal(2.0))
    c = Computed(lambda: "three")

    assert_type(unref(a), int)
    assert_type(unref(b), float)
    assert_type(unref(c), str)


def test_complex_expression():
    a = Signal(1)
    b = Signal(2.0)
    c = Computed(lambda: 3)

    result = (a + b) * c
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_reactive_method():
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
