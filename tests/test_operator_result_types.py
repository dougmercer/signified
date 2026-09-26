"""Check the runtime contracts represented by the operator inference tests."""

import math

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
