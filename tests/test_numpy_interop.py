"""Tests for NumPy interoperability.

NumPy's `ndarray` handles unknown operands itself rather than returning
`NotImplemented`, so without `__array_ufunc__ = None` an expression like
`array + reactive` silently produces an object-dtype array of `Computed` values
instead of a single reactive result. These tests pin that opt-out down.
"""

import numpy as np
import pytest

from signified import Computed, Signal, unref
from signified._mixin import _ReactiveMixIn


def test_mixin_opts_out_of_ufunc_dispatch():
    assert _ReactiveMixIn.__array_ufunc__ is None


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        (lambda a, b: a + b, [11, 22]),
        (lambda a, b: a - b, [-9, -18]),
        (lambda a, b: a * b, [10, 40]),
        (lambda a, b: a // b, [0, 0]),
        (lambda a, b: a % b, [1, 2]),
        (lambda a, b: a & b, [0, 0]),
        (lambda a, b: a | b, [11, 22]),
        (lambda a, b: a ^ b, [11, 22]),
    ],
)
def test_array_on_the_left_returns_a_reactive_value(op, expected):
    result = op(np.array([1, 2]), Signal(np.array([10, 20])))

    assert isinstance(result, Computed)
    np.testing.assert_array_equal(unref(result), np.array(expected))


def test_array_on_the_left_is_not_an_object_array():
    """The exact failure mode the opt-out exists to prevent."""
    result = np.array([1, 2]) + Signal(np.array([10, 20]))

    assert not isinstance(result, np.ndarray)
    assert isinstance(result, Computed)
    assert unref(result).dtype != np.dtype("object")


def test_array_on_the_left_stays_reactive():
    signal = Signal(np.array([10, 20]))
    result = np.array([1, 2]) + signal
    np.testing.assert_array_equal(unref(result), np.array([11, 22]))

    signal.value = np.array([100, 200])

    np.testing.assert_array_equal(unref(result), np.array([101, 202]))


def test_matmul_in_both_directions():
    matrix = np.array([[1, 2], [3, 4]])
    signal = Signal(np.array([10, 20]))

    reflected = matrix @ signal
    forward = Signal(matrix) @ np.array([10, 20])

    assert isinstance(reflected, Computed)
    assert isinstance(forward, Computed)
    np.testing.assert_array_equal(unref(reflected), np.array([50, 110]))
    np.testing.assert_array_equal(unref(forward), np.array([50, 110]))


def test_shifts_with_array_on_the_left():
    result = np.array([1, 2]) << Signal(3)

    assert isinstance(result, Computed)
    np.testing.assert_array_equal(unref(result), np.array([8, 16]))


def test_reactive_on_the_left_is_unaffected():
    signal = Signal(np.array([10, 20]))

    np.testing.assert_array_equal(unref(signal + np.array([1, 2])), np.array([11, 22]))
    np.testing.assert_array_equal(unref(signal * 2), np.array([20, 40]))


@pytest.mark.parametrize("op", [lambda a, b: a < b, lambda a, b: a >= b, lambda a, b: a > b])
def test_comparisons_with_array_on_the_left_are_reactive(op):
    result = op(np.array([1, 2]), Signal(np.array([10, 20])))

    assert isinstance(result, Computed)
    assert isinstance(unref(result), np.ndarray)


def test_calling_a_ufunc_directly_raises():
    """Opting out means ufuncs refuse the operand rather than silently coercing it."""
    signal = Signal(np.array([0.0, 1.0]))

    with pytest.raises(TypeError, match="__array_ufunc__"):
        np.sin(signal)

    with pytest.raises(TypeError, match="__array_ufunc__"):
        np.add(np.array([1.0, 2.0]), signal)


def test_rx_map_is_the_escape_hatch_for_ufuncs():
    signal = Signal(np.array([0.0, np.pi / 2]))

    result = signal.rx.map(np.sin)

    np.testing.assert_allclose(unref(result), np.array([0.0, 1.0]), atol=1e-12)
    signal.value = np.array([np.pi / 2, 0.0])
    np.testing.assert_allclose(unref(result), np.array([1.0, 0.0]), atol=1e-12)
