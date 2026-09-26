# Expected-error cases must fail checking if their ignores become unnecessary.
# pyright: reportUnnecessaryTypeIgnoreComment=true

from datetime import date, datetime, timedelta
from decimal import Decimal
from math import ceil, floor, trunc
from typing import Any, Literal, TypeVar, Union, assert_type, overload

from signified import Binding, Computed, Effect, HasValue, ReactiveValue, Signal, as_rx, computed, is_reactive, unref
from signified._protocols import _AlwaysFalse, _AlwaysTrue

T = TypeVar("T")
Numeric = Union[int, float]


def test_is_reactive_positive_narrowing(value: HasValue[int]):
    if is_reactive(value):
        assert_type(value, ReactiveValue[int])


def test_unref_distributes_over_has_value_union(value: HasValue[int] | HasValue[str]):
    assert_type(unref(value), int | str)


def test_is_reactive_distributes_over_has_value_union(value: HasValue[int] | HasValue[str]):
    if is_reactive(value):
        assert_type(value, ReactiveValue[int] | ReactiveValue[str])


def test_as_rx_preserves_wrapper_types():
    assert_type(as_rx(Signal(1)), Signal[int])
    assert_type(as_rx(Computed(lambda: 1)), Computed[int])
    assert_type(as_rx(Binding(Signal(1))), Binding[int])
    assert_type(as_rx(Signal(Signal(1))), Signal[Signal[int]])
    assert_type(as_rx(Computed(lambda: Signal(1))), Computed[Signal[int]])


def test_as_rx_distributes_over_has_value_union(value: HasValue[int] | HasValue[str]):
    assert_type(as_rx(value), ReactiveValue[int] | ReactiveValue[str])


def test_as_rx_distributes_over_larger_union(value: HasValue[int] | HasValue[str] | HasValue[bytes]):
    assert_type(as_rx(value), ReactiveValue[int] | ReactiveValue[str] | ReactiveValue[bytes])


def test_signal_and_binding_init():
    a = Signal(1)
    assert_type(a, Signal[int])
    assert_type(a.value, int)

    b = Binding(a)
    assert_type(b, Binding[int])
    assert_type(b.value, int)

    c = Binding(Binding(Binding(Binding(Signal(1.2)))))
    assert_type(c, Binding[float])
    assert_type(c.value, float)

    assert_type(c.source, Computed[float] | Signal[float] | Binding[float])
    c.value = Signal(2.0)
    assert_type(c.value, float)
    assert_type(c.set(Signal(2.0)), Binding[float])
    assert_type(c.set(3.0), Binding[float])


def test_higher_order_reactive_values():
    source = Signal(1)
    stored = Signal(source)
    calculated = Computed(lambda: source)

    assert_type(stored, Signal[Signal[int]])
    assert_type(stored.value, Signal[int])
    assert_type(unref(stored), Signal[int])
    assert_type(calculated, Computed[Signal[int]])
    assert_type(calculated.value, Signal[int])


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


def test_abs_preserves_custom_result_type():
    class Distance:
        def __abs__(self) -> float:
            return 1.0

    source = Signal(Distance())
    assert_type(abs(source), Computed[float])
    assert_type(abs(Computed(lambda: source.value)), Computed[float])
    assert_type(abs(Binding(source)), Computed[float])


def test_as_bool():
    result = Signal(1).rx.as_bool()
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)


def test_as_bool_preserves_known_truthiness(truthy: _AlwaysTrue, falsy: _AlwaysFalse, condition: bool, a: int, b: str):
    always_true = Signal[Literal[True]](True).rx.as_bool()
    always_false = Signal[Literal[False]](False).rx.as_bool()
    assert_type(always_true, Computed[Literal[True]])
    assert_type(always_false, Computed[Literal[False]])
    assert_type(Signal(truthy).rx.as_bool(), Computed[Literal[True]])
    assert_type(Signal(falsy).rx.as_bool(), Computed[Literal[False]])
    assert_type(Signal(None).rx.as_bool(), Computed[Literal[False]])
    assert_type(Binding(Signal[Literal[True]](True)).rx.as_bool(), Computed[Literal[True]])
    assert_type(always_true.rx.as_bool(), Computed[Literal[True]])
    assert_type(Signal(condition).rx.as_bool(), Computed[bool])
    assert_type(Signal(True).rx.as_bool(), Computed[bool])
    assert_type(always_true.rx.where(a, b), Computed[int])
    assert_type(always_false.rx.where(a, b), Computed[str])


def test_rx_map():
    result = Signal(2).rx.map(lambda x: x * 2)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_rx_tap():
    result = Signal(2).rx.tap(lambda x: x + 1)
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_rx_effect():
    result = Signal(2).rx.effect(lambda _x: None)
    assert_type(result, Effect)
    result.dispose()


def test_rx_len():
    result = Signal([1, 2, 3]).rx.len()
    assert_type(result, Computed[int])
    assert_type(unref(result), int)


def test_rx_len_accepts_custom_sized_values():
    class SizedValue:
        def __len__(self) -> int:
            return 3

    source = Signal(SizedValue())
    assert_type(source.rx.len(), Computed[int])
    assert_type(Computed(lambda: source.value).rx.len(), Computed[int])
    assert_type(Binding(source).rx.len(), Computed[int])


def test_rx_len_rejects_unsized_values():
    Signal(1).rx.len()  # pyright: ignore[reportAttributeAccessIssue]
    Computed(lambda: 1).rx.len()  # pyright: ignore[reportAttributeAccessIssue]
    Binding(Signal(1)).rx.len()  # pyright: ignore[reportAttributeAccessIssue]
    # Being iterable does not imply having a length.
    Signal(iter([1, 2, 3])).rx.len()  # pyright: ignore[reportAttributeAccessIssue]


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


def test_round_preserves_decimal_results(ndigits: int | None):
    source = Signal(Decimal("1.25"))
    derived = Computed(lambda: source.value)
    binding = Binding(source)
    assert_type(round(source), Computed[int])
    assert_type(round(derived), Computed[int])
    assert_type(round(binding), Computed[int])
    assert_type(round(source, None), Computed[int])
    assert_type(round(derived, None), Computed[int])
    assert_type(round(binding, None), Computed[int])
    assert_type(round(source, 1), Computed[Decimal])
    assert_type(round(derived, 1), Computed[Decimal])
    assert_type(round(binding, 1), Computed[Decimal])
    assert_type(round(source, ndigits), Computed[int] | Computed[Decimal])
    assert_type(source.__round__(ndigits), Computed[int] | Computed[Decimal])


def test_round_preserves_custom_result_types():
    class Roundable:
        @overload
        def __round__(self, ndigits: None = None) -> int: ...

        @overload
        def __round__(self, ndigits: int) -> str: ...

        def __round__(self, ndigits: int | None = None) -> int | str:
            return 1 if ndigits is None else f"rounded to {ndigits} digits"

    source = Signal(Roundable())
    derived = Computed(lambda: source.value)
    binding = Binding(source)
    assert_type(round(source), Computed[int])
    assert_type(round(derived), Computed[int])
    assert_type(round(binding), Computed[int])
    assert_type(round(source, 1), Computed[str])
    assert_type(round(derived, 1), Computed[str])
    assert_type(round(binding, 1), Computed[str])


def test_round_rejects_unsupported_values():
    round(Signal("text"))  # pyright: ignore[reportArgumentType]
    round(Computed(lambda: 1j))  # pyright: ignore[reportArgumentType]
    round(Binding(Signal(object())))  # pyright: ignore[reportArgumentType]
    round(Signal("text"), 1)  # pyright: ignore[reportCallIssue, reportArgumentType]


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


def test_unary_operators_preserve_custom_result_types():
    class UnaryValue:
        def __neg__(self) -> str:
            return "negative"

        def __pos__(self) -> bytes:
            return b"positive"

        def __invert__(self) -> int:
            return 1

    source = Signal(UnaryValue())
    derived = Computed(lambda: source.value)
    binding = Binding(source)
    assert_type(-source, Computed[str])
    assert_type(-derived, Computed[str])
    assert_type(-binding, Computed[str])
    assert_type(+source, Computed[bytes])
    assert_type(+derived, Computed[bytes])
    assert_type(+binding, Computed[bytes])
    assert_type(~source, Computed[int])
    assert_type(~derived, Computed[int])
    assert_type(~binding, Computed[int])


def test_unary_operators_reject_unsupported_values():
    _ = -Signal("text")  # pyright: ignore[reportOperatorIssue]
    _ = +Computed(lambda: "text")  # pyright: ignore[reportOperatorIssue]
    _ = ~Binding(Signal(1.5))  # pyright: ignore[reportOperatorIssue]


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


def test_trunc_preserves_decimal_and_custom_result_types():
    decimal = Signal(Decimal("1.5"))
    assert_type(trunc(decimal), Computed[int])
    assert_type(trunc(Computed(lambda: decimal.value)), Computed[int])
    assert_type(trunc(Binding(decimal)), Computed[int])

    class IntegralResult(int):
        pass

    class Truncatable:
        def __trunc__(self) -> IntegralResult:
            return IntegralResult(1)

    source = Signal(Truncatable())
    assert_type(trunc(source), Computed[IntegralResult])
    assert_type(trunc(Computed(lambda: source.value)), Computed[IntegralResult])
    assert_type(trunc(Binding(source)), Computed[IntegralResult])


def test_trunc_rejects_unsupported_values():
    trunc(Signal("text"))  # pyright: ignore[reportArgumentType]
    trunc(Computed(lambda: 1j))  # pyright: ignore[reportArgumentType]
    trunc(Binding(Signal(object())))  # pyright: ignore[reportArgumentType]


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
    result = Signal([1, 2, 3]).rx.contains(2)
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)

    text_contains = Signal("abc").rx.contains("b")
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


def test_floordiv():
    int_div = Signal(10) // Signal(3)
    assert_type(int_div, Computed[int])
    assert_type(unref(int_div), int)

    bool_div = Signal(True) // Signal(2)
    assert_type(bool_div, Computed[int])
    assert_type(unref(bool_div), int)

    numeric_div = Signal(10) // Signal(2.0)
    assert_type(numeric_div, Computed[float])
    assert_type(unref(numeric_div), float)

    float_div = Signal(10.0) // Signal(2)
    assert_type(float_div, Computed[float])
    assert_type(unref(float_div), float)


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
    assert_type(result, Computed[int])


def test_mod():
    modded = Signal(17) % Signal(5)
    assert_type(modded, Computed[int])
    assert_type(unref(modded), int)

    bool_modded = Signal(True) % Signal(2)
    assert_type(bool_modded, Computed[int])
    assert_type(unref(bool_modded), int)

    float_modded = Signal(17.0) % Signal(5)
    assert_type(float_modded, Computed[float])
    assert_type(unref(float_modded), float)


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
    assert_type(numeric_product, Computed[float])
    assert_type(unref(numeric_product), float)


def test_rx_ne():
    result = Signal(5).rx.ne(Signal(6))
    assert_type(result, Computed[bool])
    assert_type(unref(result), bool)
    # Comparing reactive objects with `!=` returns an ordinary bool.
    assert_type(Signal(5) != Signal(6), bool)


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
    assert_type(float_powered, Computed[float])
    assert_type(unref(float_powered), float)


def test_sub():
    int_difference = Signal(10) - Signal(3)
    assert_type(int_difference, Computed[int])
    assert_type(unref(int_difference), int)

    numeric_difference = Signal(10) - Signal(2.0)
    assert_type(numeric_difference, Computed[float])
    assert_type(unref(numeric_difference), float)


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
    assert_type(numeric_div, Computed[float])
    assert_type(unref(numeric_div), float)


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
    assert_type(numeric_product, Computed[float])
    assert_type(unref(numeric_product), float)


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
    assert_type(float_powered, Computed[float])
    assert_type(unref(float_powered), float)


def test_rsub():
    int_difference = 15 - Signal(10)
    assert_type(int_difference, Computed[int])
    assert_type(unref(int_difference), int)

    numeric_difference = 15 - Signal(2.0)
    assert_type(numeric_difference, Computed[float])
    assert_type(unref(numeric_difference), float)


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


def test_getitem_reactive_slices():
    key = Signal(slice(1, None))
    numbers = Signal([1, 2, 3])
    tuple_values = Signal[tuple[int, ...]]((1, 2, 3))
    chars = Signal("abc")

    assert_type(numbers[key], Computed[list[int]])
    assert_type(tuple_values[key], Computed[tuple[int, ...]])
    assert_type(chars[key], Computed[str])
    assert_type(numbers[Computed(lambda: key.value)], Computed[list[int]])
    assert_type(tuple_values[Binding(key)], Computed[tuple[int, ...]])
    assert_type(chars[Binding(key)], Computed[str])


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

    result = condition.rx.where(a, b)
    assert_type(result, Computed[Numeric])
    assert_type(unref(result), Numeric)


def test_where_protocol_annotations(a: int, b: str, truthy: _AlwaysTrue, falsy: _AlwaysFalse):
    assert_type(Signal(truthy).rx.where(a, b), Computed[int])
    assert_type(Signal(falsy).rx.where(a, b), Computed[str])


def test_where_literal_conditions(a: int, b: str):
    truthy = Signal[Literal[True]](True)
    falsy = Signal[Literal[False]](False)
    assert_type(truthy.rx.where(a, b), Computed[int])
    assert_type(falsy.rx.where(a, b), Computed[str])
    assert_type(Signal(None).rx.where(a, b), Computed[str])

    assert_type(truthy.rx.where(Signal(a), Signal(b)), Computed[int])
    assert_type(falsy.rx.where(Signal(a), Signal(b)), Computed[str])
    assert_type(Binding(truthy).rx.where(a, b), Computed[int])
    assert_type(Binding(falsy).rx.where(a, b), Computed[str])
    assert_type(Computed[Literal[True]](lambda: truthy.value).rx.where(a, b), Computed[int])
    assert_type(Computed[Literal[False]](lambda: falsy.value).rx.where(a, b), Computed[str])


def test_where_structural_truthiness(a: int, b: str):
    class AlwaysTruthy:
        def __bool__(self) -> Literal[True]:
            return True

    class AlwaysFalsy:
        def __bool__(self) -> Literal[False]:
            return False

    assert_type(Signal(AlwaysTruthy()).rx.where(a, b), Computed[int])
    assert_type(Signal(AlwaysFalsy()).rx.where(a, b), Computed[str])


def test_where_uncertain_truthiness_retains_union(
    a: int, b: str, condition: bool, either: _AlwaysTrue | _AlwaysFalse, unknown: object
):
    assert_type(Signal(condition).rx.where(a, b), Computed[int | str])
    assert_type(Signal(either).rx.where(a, b), Computed[int | str])
    assert_type(Signal(unknown).rx.where(a, b), Computed[int | str])
    # Inference widens the initial True to bool because the signal is mutable.
    mutable = Signal(True)
    mutable.value = False
    assert_type(mutable.rx.where(a, b), Computed[int | str])


def test_where_union_with_same_truthiness(
    a: int, b: str, truthy: _AlwaysTrue | Literal[True], falsy: _AlwaysFalse | None
):
    assert_type(Signal[_AlwaysTrue | Literal[True]](truthy).rx.where(a, b), Computed[int])
    assert_type(Signal(falsy).rx.where(a, b), Computed[str])


def test_unref():
    a = Signal(1)
    b = Binding(Signal(2.0))
    c = Computed(lambda: "three")

    assert_type(unref(a), int)
    assert_type(unref(b), float)
    assert_type(unref(c), str)


def test_complex_expression():
    a = Signal(1)
    b = Signal(2.0)
    c = Computed(lambda: 3)

    result = (a + b) * c
    assert_type(result, Computed[float])
    assert_type(unref(result), float)


def test_resolution_registration_and_contexts():
    from typing import Any

    from signified import ResolveContext, batch, deep_unref, untracked

    class Box:
        def __init__(self, child: object) -> None:
            self.child = child

    @deep_unref.register(Box)
    def resolve_box(box: Box, resolve: ResolveContext) -> Box:
        return Box(resolve(box.child))

    with batch(), untracked():
        assert_type(deep_unref(Box(Signal(1))), Any)
        assert_type(unref(Signal(Signal(1))), Signal[int])
        assert_type(resolve_box(Box(1), ResolveContext({})), Box)


def test_floor_division_numeric_promotion():
    assert_type(Signal(10) // 2, Computed[int])
    assert_type(Signal(10.0) // Signal(2.0), Computed[float])
    assert_type(Signal(10.0) // 2, Computed[float])
    assert_type(Signal(10) // 2.0, Computed[float])
    assert_type(10.0 // Signal(2), Computed[float])
    assert_type(10 // Signal(2.0), Computed[float])
    assert_type(Signal(True) // Signal(True), Computed[int])
    assert_type(Signal(2) // Signal(True), Computed[int])
    assert_type(True // Signal(2), Computed[int])
    assert_type(Signal(True) // Signal(2.0), Computed[float])
    assert_type(Signal(2.0) // Signal(True), Computed[float])
    assert_type(2.0 // Signal(True), Computed[float])
    assert_type(True // Signal(2.0), Computed[float])
    assert_type(Binding(Signal(10)) // Computed(lambda: 2.0), Computed[float])


def test_modulo_numeric_promotion():
    assert_type(Signal(10) % 3, Computed[int])
    assert_type(Signal(10.0) % Signal(3.0), Computed[float])
    assert_type(Signal(10) % Signal(3.0), Computed[float])
    assert_type(Signal(10.0) % 3, Computed[float])
    assert_type(Signal(10) % 3.0, Computed[float])
    assert_type(10.0 % Signal(3), Computed[float])
    assert_type(10 % Signal(3.0), Computed[float])
    assert_type(Signal(True) % Signal(True), Computed[int])
    assert_type(Signal(2) % Signal(True), Computed[int])
    assert_type(True % Signal(2), Computed[int])
    assert_type(Signal(True) % Signal(2.0), Computed[float])
    assert_type(Signal(2.0) % Signal(True), Computed[float])
    assert_type(2.0 % Signal(True), Computed[float])
    assert_type(True % Signal(2.0), Computed[float])
    assert_type(Binding(Signal(10)) % Computed(lambda: 3.0), Computed[float])


def test_multiplication_numeric_promotion():
    assert_type(Signal(2) * 3, Computed[int])
    assert_type(Signal(2.0) * Signal(3), Computed[float])
    assert_type(Signal(2) * 3.0, Computed[float])
    assert_type(2.0 * Signal(3), Computed[float])
    assert_type(Signal(True) * Signal(True), Computed[int])
    assert_type(Signal(2) * Signal(True), Computed[int])
    assert_type(True * Signal(2), Computed[int])
    assert_type(Signal(True) * Signal(2.0), Computed[float])
    assert_type(Signal(2.0) * Signal(True), Computed[float])
    assert_type(2.0 * Signal(True), Computed[float])
    assert_type(True * Signal(2.0), Computed[float])
    assert_type(Signal(2j) * Signal(3), Computed[complex])
    assert_type(Signal(2) * Signal(3j), Computed[complex])
    assert_type(Signal(2.0) * Signal(3j), Computed[complex])
    assert_type(Signal(2j) * Signal(True), Computed[complex])
    assert_type(2j * Signal(3), Computed[complex])
    assert_type(2 * Signal(3j), Computed[complex])
    assert_type(2j * Signal(3.0), Computed[complex])
    assert_type(True * Signal(3j), Computed[complex])
    assert_type(Binding(Signal(2)) * Computed(lambda: 3.0), Computed[float])


def test_subtraction_result_types():
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 2)
    day = timedelta(days=1)
    assert_type(Signal(end) - Signal(start), Computed[timedelta])
    assert_type(Signal(end) - start, Computed[timedelta])
    assert_type(end - Signal(start), Computed[timedelta])
    assert_type(Signal(end) - Signal(day), Computed[datetime])
    assert_type(Signal(end) - day, Computed[datetime])
    assert_type(end - Signal(day), Computed[datetime])
    assert_type(Signal(date(2026, 1, 2)) - date(2026, 1, 1), Computed[timedelta])
    assert_type(Signal(date(2026, 1, 2)) - Signal(day), Computed[date])
    assert_type(date(2026, 1, 2) - Signal(date(2026, 1, 1)), Computed[timedelta])
    assert_type(date(2026, 1, 2) - Signal(day), Computed[date])
    assert_type(Signal(day) - Signal(day), Computed[timedelta])
    assert_type(Signal({1, 2}) - Signal({2}), Computed[set[int]])
    assert_type({1, 2} - Signal({2}), Computed[set[int]])

    class Distance:
        def __sub__(self, other: int) -> str:
            if not isinstance(other, int):
                return NotImplemented
            return str(other)

    assert_type(Signal(Distance()) - Signal(1), Computed[str])
    assert_type(Signal(Distance()) - 1, Computed[str])
    assert_type(Distance() - Signal(1), Computed[str])


def test_subtraction_numeric_promotion():
    assert_type(Signal(2) - 3, Computed[int])
    assert_type(Signal(2.0) - Signal(3), Computed[float])
    assert_type(Signal(2) - 3.0, Computed[float])
    assert_type(2.0 - Signal(3), Computed[float])
    assert_type(Signal(True) - Signal(True), Computed[int])
    assert_type(Signal(2) - Signal(True), Computed[int])
    assert_type(True - Signal(2), Computed[int])
    assert_type(Signal(True) - Signal(2.0), Computed[float])
    assert_type(Signal(2.0) - Signal(True), Computed[float])
    assert_type(2.0 - Signal(True), Computed[float])
    assert_type(True - Signal(2.0), Computed[float])
    assert_type(Signal(2j) - Signal(3), Computed[complex])
    assert_type(Signal(2) - Signal(3j), Computed[complex])
    assert_type(Signal(2.0) - Signal(3j), Computed[complex])
    assert_type(Signal(2j) - Signal(True), Computed[complex])
    assert_type(2j - Signal(3), Computed[complex])
    assert_type(2 - Signal(3j), Computed[complex])
    assert_type(2j - Signal(3.0), Computed[complex])
    assert_type(True - Signal(3j), Computed[complex])
    assert_type(Binding(Signal(2)) - Computed(lambda: 3.0), Computed[float])


def test_bitwise_bool_int_promotion():
    assert_type(Signal(True) & Signal(1), Computed[int])
    assert_type(Signal(1) & Signal(True), Computed[int])
    assert_type(Signal(True) & 1, Computed[int])
    assert_type(Signal(1) & True, Computed[int])
    assert_type(True & Signal(1), Computed[int])
    assert_type(1 & Signal(True), Computed[int])
    assert_type(Signal(True) & False, Computed[bool])
    assert_type(Signal(True) & Signal(False), Computed[bool])
    assert_type(True & Signal(False), Computed[bool])
    assert_type(Binding(Signal(True)) & Computed(lambda: 1), Computed[int])
    assert_type(Signal({1}) & Signal({2}), Computed[set[int]])
    assert_type(Signal(True) | Signal(1), Computed[int])
    assert_type(Signal(1) | Signal(True), Computed[int])
    assert_type(Signal(True) | 1, Computed[int])
    assert_type(Signal(1) | True, Computed[int])
    assert_type(True | Signal(1), Computed[int])
    assert_type(1 | Signal(True), Computed[int])
    assert_type(Signal(True) | False, Computed[bool])
    assert_type(Signal(True) | Signal(False), Computed[bool])
    assert_type(True | Signal(False), Computed[bool])
    assert_type(Binding(Signal(True)) | Computed(lambda: 1), Computed[int])
    assert_type(Signal({1}) | Signal({2}), Computed[set[int]])
    assert_type(Signal(True) ^ Signal(1), Computed[int])
    assert_type(Signal(1) ^ Signal(True), Computed[int])
    assert_type(Signal(True) ^ 1, Computed[int])
    assert_type(Signal(1) ^ True, Computed[int])
    assert_type(True ^ Signal(1), Computed[int])
    assert_type(1 ^ Signal(True), Computed[int])
    assert_type(Signal(True) ^ False, Computed[bool])
    assert_type(Signal(True) ^ Signal(False), Computed[bool])
    assert_type(True ^ Signal(False), Computed[bool])
    assert_type(Binding(Signal(True)) ^ Computed(lambda: 1), Computed[int])
    assert_type(Signal({1}) ^ Signal({2}), Computed[set[int]])


def test_addition_numeric_promotion():
    assert_type(Signal(2) + 3, Computed[int])
    assert_type(Signal(2.0) + Signal(3), Computed[float])
    assert_type(Signal(2) + 3.0, Computed[float])
    assert_type(2.0 + Signal(3), Computed[float])
    assert_type(Signal(True) + Signal(True), Computed[int])
    assert_type(Signal(2) + Signal(True), Computed[int])
    assert_type(True + Signal(2), Computed[int])
    assert_type(Signal(True) + Signal(2.0), Computed[float])
    assert_type(Signal(2.0) + Signal(True), Computed[float])
    assert_type(2.0 + Signal(True), Computed[float])
    assert_type(True + Signal(2.0), Computed[float])
    assert_type(Signal(2j) + Signal(3), Computed[complex])
    assert_type(Signal(2) + Signal(3j), Computed[complex])
    assert_type(Signal(2.0) + Signal(3j), Computed[complex])
    assert_type(Signal(2j) + Signal(True), Computed[complex])
    assert_type(2j + Signal(3), Computed[complex])
    assert_type(2 + Signal(3j), Computed[complex])
    assert_type(2j + Signal(3.0), Computed[complex])
    assert_type(True + Signal(3j), Computed[complex])
    assert_type(Binding(Signal(2)) + Computed(lambda: 3.0), Computed[float])


def test_truediv_numeric_promotion():
    assert_type(Signal(7) / Signal(2), Computed[float])
    assert_type(Signal(7) / 2.0, Computed[float])
    assert_type(Signal(7.0) / True, Computed[float])
    assert_type(Signal(True) / Signal(True), Computed[float])
    assert_type(2.0 / Signal(3), Computed[float])
    assert_type(True / Signal(2.0), Computed[float])
    assert_type(Signal(2) / Signal(3j), Computed[complex])
    assert_type(Signal(2.0) / Signal(3j), Computed[complex])
    assert_type(Signal(True) / Signal(3j), Computed[complex])
    assert_type(Signal(2j) / Signal(3), Computed[complex])
    assert_type(Signal(2j) / Signal(3.0), Computed[complex])
    assert_type(Signal(2j) / Signal(3j), Computed[complex])
    assert_type(2j / Signal(3), Computed[complex])
    assert_type(2 / Signal(3j), Computed[complex])
    assert_type(2j / Signal(3.0), Computed[complex])
    assert_type(True / Signal(3j), Computed[complex])
    assert_type(Binding(Signal(2)) / Computed(lambda: 3.0), Computed[float])


def test_pow_numeric_promotion():
    # Value-dependent powers have known typing gaps; see type_inference_todo.py.
    assert_type(Signal(2.0) ** Signal(3), Computed[float])
    assert_type(Signal(2.0) ** True, Computed[float])
    assert_type(2.0 ** Signal(3), Computed[float])
    assert_type(Signal(2) ** Signal(3j), Computed[complex])
    assert_type(Signal(2.0) ** Signal(3j), Computed[complex])
    assert_type(Signal(True) ** Signal(3j), Computed[complex])
    assert_type(Signal(2j) ** Signal(3), Computed[complex])
    assert_type(Signal(2j) ** Signal(3.0), Computed[complex])
    assert_type(Signal(2j) ** Signal(3j), Computed[complex])
    assert_type(2j ** Signal(3), Computed[complex])
    assert_type(2 ** Signal(3j), Computed[complex])
    assert_type(2j ** Signal(3.0), Computed[complex])


def test_shift_bool_int_promotion():
    assert_type(Signal(8) << 2, Computed[int])
    assert_type(Signal(True) << 1, Computed[int])
    assert_type(Signal(True) << Signal(True), Computed[int])
    assert_type(Signal(1) << Signal(True), Computed[int])
    assert_type(Signal(8) >> 2, Computed[int])
    assert_type(Signal(True) >> Signal(1), Computed[int])
    assert_type(Signal(1) >> Signal(True), Computed[int])
    assert_type(Binding(Signal(True)) << Computed(lambda: 1), Computed[int])


def test_divmod_result_types():
    assert_type(divmod(Signal(10), 3), Computed[tuple[int, int]])
    assert_type(divmod(Signal(True), Signal(True)), Computed[tuple[int, int]])
    assert_type(divmod(Signal(10), Signal(True)), Computed[tuple[int, int]])
    assert_type(divmod(Signal(10.0), 3), Computed[tuple[float, float]])
    assert_type(divmod(Signal(10), 3.0), Computed[tuple[float, float]])
    assert_type(divmod(Signal(True), 3.0), Computed[tuple[float, float]])
    assert_type(divmod(3.0, Signal(10)), Computed[tuple[float, float]])
    assert_type(divmod(3, Signal(10.0)), Computed[tuple[float, float]])
    assert_type(divmod(Signal(Decimal(10)), Decimal(3)), Computed[tuple[Decimal, Decimal]])
    assert_type(divmod(Decimal(10), Signal(Decimal(3))), Computed[tuple[Decimal, Decimal]])


def test_addition_result_types():
    day = timedelta(days=1)
    assert_type(Signal(date(2026, 1, 1)) + day, Computed[date])
    assert_type(Signal(date(2026, 1, 1)) + Signal(day), Computed[date])
    assert_type(Signal(datetime(2026, 1, 1)) + Signal(day), Computed[datetime])
    assert_type(day + Signal(date(2026, 1, 1)), Computed[date])
    assert_type(Signal(day) + Signal(day), Computed[timedelta])


def test_operators_preserve_declared_return_types():
    """A user type's own operator return type survives the reactive wrapper."""

    class Vec:
        def __mul__(self, other: int) -> "Vec": ...
        def __matmul__(self, other: "Vec") -> float: ...
        def __truediv__(self, other: int) -> "Vec": ...
        def __floordiv__(self, other: int) -> "Vec": ...
        def __mod__(self, other: int) -> str: ...
        def __pow__(self, other: int) -> "Vec": ...
        def __lshift__(self, other: int) -> bytes: ...
        def __rshift__(self, other: int) -> bytes: ...

    v = Signal(Vec())
    assert_type(v * 2, Computed[Vec])
    assert_type(v @ Vec(), Computed[float])
    assert_type(v / 2, Computed[Vec])
    assert_type(v // 2, Computed[Vec])
    assert_type(v % 2, Computed[str])
    assert_type(v**2, Computed[Vec])
    assert_type(v << 2, Computed[bytes])
    assert_type(v >> 2, Computed[bytes])
    assert_type(v * Signal(2), Computed[Vec])
    assert_type(Binding(Signal(Vec())) @ Computed(lambda: Vec()), Computed[float])


def test_reflected_operators_preserve_declared_return_types():
    """The same holds when the reactive value is on the right-hand side."""

    class Scale:
        def __mul__(self, other: int) -> str: ...
        def __truediv__(self, other: int) -> str: ...
        def __floordiv__(self, other: int) -> str: ...
        def __mod__(self, other: int) -> str: ...
        def __pow__(self, other: int) -> str: ...

    n = Signal(2)
    assert_type(Scale() * n, Computed[str])
    assert_type(Scale() / n, Computed[str])
    assert_type(Scale() // n, Computed[str])
    assert_type(Scale() % n, Computed[str])
    assert_type(Scale() ** n, Computed[str])


def test_reflected_shift_and_matmul():
    class Row:
        def __matmul__(self, other: "Row") -> float: ...

    class Bits:
        def __lshift__(self, other: int) -> bytes: ...
        def __rshift__(self, other: int) -> bytes: ...

    assert_type(1 << Signal(2), Computed[int])
    assert_type(32 >> Signal(2), Computed[int])
    assert_type(True << Signal(2), Computed[int])
    assert_type(Signal(1) << Signal(2), Computed[int])
    assert_type(Bits() << Signal(2), Computed[bytes])
    assert_type(Bits() >> Signal(2), Computed[bytes])
    assert_type(Row() @ Signal(Row()), Computed[float])
    assert_type(1 << Binding(Signal(2)), Computed[int])


def test_ceil_and_floor_preserve_custom_results_and_numeric_fallbacks():
    class IntegralResult(int):
        pass

    class Roundable:
        def __ceil__(self) -> IntegralResult:
            return IntegralResult(2)

        def __floor__(self) -> IntegralResult:
            return IntegralResult(1)

        def __float__(self) -> float:
            return 1.5

    # The explicit rounding method takes precedence over numeric conversion.
    source = Signal(Roundable())
    assert_type(ceil(source), Computed[IntegralResult])
    assert_type(floor(source), Computed[IntegralResult])
    assert_type(ceil(Computed(lambda: source.value)), Computed[IntegralResult])
    assert_type(floor(Computed(lambda: source.value)), Computed[IntegralResult])
    assert_type(ceil(Binding(source)), Computed[IntegralResult])
    assert_type(floor(Binding(source)), Computed[IntegralResult])
    assert_type(ceil(Signal(Decimal("1.5"))), Computed[int])
    assert_type(floor(Signal(Decimal("1.5"))), Computed[int])

    class Floatable:
        def __float__(self) -> float:
            return 1.5

    class Indexable:
        def __index__(self) -> int:
            return 2

    assert_type(ceil(Signal(Floatable())), Computed[int])
    assert_type(floor(Binding(Signal(Floatable()))), Computed[int])
    assert_type(ceil(Computed(Indexable)), Computed[int])
    assert_type(floor(Signal(Indexable())), Computed[int])


def test_ceil_and_floor_reject_unsupported_values():
    ceil(Signal("text"))  # pyright: ignore[reportCallIssue, reportArgumentType]
    floor(Signal("text"))  # pyright: ignore[reportCallIssue, reportArgumentType]
    ceil(Computed(lambda: 1j))  # pyright: ignore[reportCallIssue, reportArgumentType]
    floor(Computed(lambda: 1j))  # pyright: ignore[reportCallIssue, reportArgumentType]
    ceil(Binding(Signal(object())))  # pyright: ignore[reportCallIssue, reportArgumentType]
    floor(Binding(Signal(object())))  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_bitwise_operators_preserve_custom_results():
    class Bits:
        def __and__(self, other: int) -> str: ...
        def __or__(self, other: int) -> bytes: ...
        def __xor__(self, other: int) -> tuple[int, int]: ...

    source = Signal(Bits())
    assert_type(source & 1, Computed[str])
    assert_type(source | 1, Computed[bytes])
    assert_type(source ^ 1, Computed[tuple[int, int]])
    assert_type(source & Signal(1), Computed[str])
    assert_type(Computed(lambda: source.value) | Binding(Signal(1)), Computed[bytes])
    assert_type(Binding(source) ^ Computed(lambda: 1), Computed[tuple[int, int]])
    assert_type(Bits() & Signal(1), Computed[str])
    assert_type(Bits() | Computed(lambda: 1), Computed[bytes])
    assert_type(Bits() ^ Binding(Signal(1)), Computed[tuple[int, int]])


def test_ordering_preserves_custom_and_reflected_results():
    class Mask:
        pass

    class Comparable:
        def __lt__(self, other: int) -> Mask: ...
        def __le__(self, other: int) -> Mask: ...
        def __gt__(self, other: int) -> Mask: ...
        def __ge__(self, other: int) -> Mask: ...

    source = Signal(Comparable())
    assert_type(source < 1, Computed[Mask])
    assert_type(source <= Signal(1), Computed[Mask])
    assert_type(Computed(lambda: source.value) > 1, Computed[Mask])
    assert_type(Binding(source) >= 1, Computed[Mask])
    assert_type(1 < source, Computed[Mask])
    assert_type(1 <= source, Computed[Mask])
    assert_type(1 > source, Computed[Mask])
    assert_type(1 >= source, Computed[Mask])
    assert_type(Signal(1) < source, Computed[Mask])
    assert_type(Signal(1) <= source, Computed[Mask])
    assert_type(Signal(1) > source, Computed[Mask])
    assert_type(Signal(1) >= source, Computed[Mask])
    assert_type(Comparable() < Signal(1), Computed[Mask])
    assert_type(Comparable() <= Signal(1), Computed[Mask])
    assert_type(Comparable() > Signal(1), Computed[Mask])
    assert_type(Comparable() >= Signal(1), Computed[Mask])


def test_ordering_numeric_and_container_results():
    assert_type(Signal(1) < Signal(1.5), Computed[bool])
    assert_type(Signal(1.5) <= Signal(1), Computed[bool])
    assert_type(1.5 > Signal(1), Computed[bool])
    assert_type(1 >= Signal(1.5), Computed[bool])
    assert_type(Signal(Decimal("1.5")) < Signal(2), Computed[bool])
    assert_type(Signal(2) < Signal(Decimal("1.5")), Computed[bool])
    assert_type(Signal({1}) < Signal({1, 2}), Computed[bool])
    assert_type(Signal([1]) <= Signal([2]), Computed[bool])
    assert_type(Signal("a") > Signal("b"), Computed[bool])


def test_binary_operators_reject_unsupported_operands():
    _ = Signal(1) + "text"  # pyright: ignore[reportOperatorIssue]
    _ = "text" + Signal(1)  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) - "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) * object()  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) / "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) // "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) % "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) ** "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) @ 2  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) << 1.5  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) >> 1.5  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) & 1.5  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) | 1.5  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) ^ 1.5  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) < "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) <= "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) > "text"  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) >= "text"  # pyright: ignore[reportOperatorIssue]

    # An arbitrary .value property must not make a plain object an operand.
    class ValueBox:
        value: int = 1

    _ = Signal(1) + ValueBox()  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) < ValueBox()  # pyright: ignore[reportOperatorIssue]


def test_right_hand_operator_methods_preserve_results():
    class RightOnly:
        def __radd__(self, other: int) -> str: ...
        def __rsub__(self, other: int) -> str: ...
        def __rmul__(self, other: int) -> str: ...
        def __rmatmul__(self, other: int) -> str: ...
        def __rtruediv__(self, other: int) -> str: ...
        def __rfloordiv__(self, other: int) -> str: ...
        def __rmod__(self, other: int) -> str: ...
        def __rpow__(self, other: int) -> str: ...
        def __rlshift__(self, other: int) -> str: ...
        def __rrshift__(self, other: int) -> str: ...
        def __rand__(self, other: int) -> str: ...
        def __ror__(self, other: int) -> str: ...
        def __rxor__(self, other: int) -> str: ...

    source = Signal(RightOnly())
    assert_type(1 + source, Computed[str])
    assert_type(Signal(1) + source, Computed[str])
    assert_type(Signal(1) + RightOnly(), Computed[str])
    assert_type(1 - source, Computed[str])
    assert_type(Signal(1) - source, Computed[str])
    assert_type(Signal(1) - RightOnly(), Computed[str])
    assert_type(1 * source, Computed[str])
    assert_type(Signal(1) * source, Computed[str])
    assert_type(Signal(1) * RightOnly(), Computed[str])
    assert_type(1 @ source, Computed[str])
    assert_type(Signal(1) @ source, Computed[str])
    assert_type(Signal(1) @ RightOnly(), Computed[str])
    assert_type(1 / source, Computed[str])
    assert_type(Signal(1) / source, Computed[str])
    assert_type(Signal(1) / RightOnly(), Computed[str])
    assert_type(1 // source, Computed[str])
    assert_type(Signal(1) // source, Computed[str])
    assert_type(Signal(1) // RightOnly(), Computed[str])
    assert_type(1 % source, Computed[str])
    assert_type(Signal(1) % source, Computed[str])
    assert_type(Signal(1) % RightOnly(), Computed[str])
    assert_type(1**source, Computed[str])
    assert_type(Signal(1) ** source, Computed[str])
    assert_type(Signal(1) ** RightOnly(), Computed[str])
    assert_type(1 << source, Computed[str])
    assert_type(Signal(1) << source, Computed[str])
    assert_type(Signal(1) << RightOnly(), Computed[str])
    assert_type(1 >> source, Computed[str])
    assert_type(Signal(1) >> source, Computed[str])
    assert_type(Signal(1) >> RightOnly(), Computed[str])
    assert_type(1 & source, Computed[str])
    assert_type(Signal(1) & source, Computed[str])
    assert_type(Signal(1) & RightOnly(), Computed[str])
    assert_type(1 | source, Computed[str])
    assert_type(Signal(1) | source, Computed[str])
    assert_type(Signal(1) | RightOnly(), Computed[str])
    assert_type(1 ^ source, Computed[str])
    assert_type(Signal(1) ^ source, Computed[str])
    assert_type(Signal(1) ^ RightOnly(), Computed[str])
    assert_type(1 + Computed(lambda: source.value), Computed[str])
    assert_type(Computed(lambda: 1) + Binding(source), Computed[str])
    assert_type(source.__radd__(Signal(1)), Computed[str])
    assert_type(source.__rsub__(Signal(1)), Computed[str])
    assert_type(source.__rmul__(Signal(1)), Computed[str])
    assert_type(source.__rmatmul__(Signal(1)), Computed[str])
    assert_type(source.__rtruediv__(Signal(1)), Computed[str])
    assert_type(source.__rfloordiv__(Signal(1)), Computed[str])
    assert_type(source.__rmod__(Signal(1)), Computed[str])
    assert_type(source.__rpow__(Signal(1)), Computed[str])
    assert_type(source.__rlshift__(Signal(1)), Computed[str])
    assert_type(source.__rrshift__(Signal(1)), Computed[str])
    assert_type(source.__rand__(Signal(1)), Computed[str])
    assert_type(source.__ror__(Signal(1)), Computed[str])
    assert_type(source.__rxor__(Signal(1)), Computed[str])


def test_set_and_dictionary_operator_results():
    assert_type(Signal({1}) | Signal({"a"}), Computed[set[int | str]])
    assert_type(Signal({1}) & Signal({"a"}), Computed[set[int]])
    assert_type(Signal({1}) ^ Signal({"a"}), Computed[set[int | str]])
    assert_type(Signal({1: "a"}) | Signal({"b": 2}), Computed[dict[int | str, str | int]])


def test_binary_operators_reject_unsupported_reactive_operands():
    _ = Signal(1) + Signal("text")  # pyright: ignore[reportOperatorIssue]
    _ = Binding(Signal(1)) & Computed(lambda: 1.5)  # pyright: ignore[reportOperatorIssue]
    _ = Signal(1) < Signal("text")  # pyright: ignore[reportOperatorIssue]


def test_binary_operators_prefer_left_method():
    class Left:
        def __add__(self, other: "Right") -> str: ...

    class Right:
        def __radd__(self, other: Left) -> bytes: ...

    assert_type(Signal(Left()) + Signal(Right()), Computed[str])
    assert_type(Signal(Left()) + Right(), Computed[str])
    assert_type(Left() + Signal(Right()), Computed[str])
    assert_type(Signal(Right()).__radd__(Signal(Left())), Computed[str])


def test_numpy_ordering_preserves_array_results():
    import numpy as np
    from numpy.typing import NDArray

    array: NDArray[np.float64] = np.array([1.0, 2.0])
    assert_type(Signal(array) + Signal(array), Computed[NDArray[np.float64]])
    assert_type(Signal(array) < 1.0, Computed[NDArray[np.bool_]])
    assert_type(Signal(1.0) < Signal(array), Computed[NDArray[np.bool_]])
    assert_type(Binding(Signal(array)) >= Computed(lambda: array), Computed[NDArray[np.bool_]])
