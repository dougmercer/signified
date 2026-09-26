"""Check the runtime contracts represented by the operator inference tests."""

import math
import operator

import pytest

from signified import Binding, Computed, Signal


class IntegralResult(int):
    pass


class Roundable:
    def __init__(self, value: int):
        self.value = value

    def __ceil__(self) -> IntegralResult:
        return IntegralResult(self.value + 1)

    def __floor__(self) -> IntegralResult:
        return IntegralResult(self.value)

    def __float__(self) -> float:
        # The explicit rounding methods must take precedence.
        return 100.5


@pytest.mark.parametrize("operation", [math.ceil, math.floor])
@pytest.mark.parametrize("view", [lambda s: s, lambda s: Computed(lambda: s.value), Binding])
def test_custom_rounding_results_remain_reactive(operation, view):
    source = Signal(Roundable(1))
    result = operation(view(source))
    assert isinstance(result, Computed)
    assert type(result.value) is IntegralResult
    assert result.value == operation(source.value)
    source.value = Roundable(4)
    assert type(result.value) is IntegralResult
    assert result.value == operation(source.value)


def test_rounding_numeric_conversion_fallbacks():
    class Floatable:
        def __float__(self) -> float:
            return 1.5

    class Indexable:
        def __index__(self) -> int:
            return 2

    for value in (Floatable(), Indexable()):
        assert math.ceil(Signal(value)).value == math.ceil(value)
        assert math.floor(Signal(value)).value == math.floor(value)


class CustomOperators:
    def __init__(self, value: int):
        self.value = value

    def _result(self, other: int) -> list[bool]:
        return [self.value < other, self.value == other]

    __lt__ = __le__ = __gt__ = __ge__ = _result
    __and__ = __or__ = __xor__ = _result


@pytest.mark.parametrize(
    "operation", [operator.lt, operator.le, operator.gt, operator.ge, operator.and_, operator.or_, operator.xor]
)
def test_custom_operator_results_remain_reactive(operation):
    source = Signal(CustomOperators(1))
    other = Signal(2)
    result = operation(Binding(source), Computed(lambda: other.value))
    assert result.value == [True, False]
    source.value = CustomOperators(2)
    assert result.value == [False, True]
    other.value = 0
    assert result.value == [False, False]
