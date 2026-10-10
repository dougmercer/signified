"""Core propagation semantics the Rust engine must share with the Python engine."""

import math

import pytest

from signified import Computed, Signal, untracked


def test_operators_build_nodes_of_the_engine_under_test():
    assert isinstance(Signal(1) + 1, Computed)
    assert isinstance(Signal("a").upper(), Computed)


def test_signal_write_changes_version_only_when_value_changes():
    s = Signal(1)
    before = s._version
    s.value = 1
    assert s._version == before
    s.value = 2
    assert s.value == 2
    assert s._version > before


def test_operator_chain_propagates():
    s = Signal(2)
    out = (s + 1) * 10
    assert out.value == 30
    s.value = 4
    assert out.value == 50


def test_computed_is_lazy_and_cached():
    calls = []
    s = Signal(1)
    c = Computed(lambda: calls.append(1) or s.value * 2)
    assert calls == []
    assert c.value == 2
    assert c.value == 2
    assert len(calls) == 1
    s.value = 5
    assert len(calls) == 1  # invalidation alone does not recompute
    assert c.value == 10
    assert len(calls) == 2


def test_diamond_recomputes_join_once_per_change():
    calls = []
    s = Signal(1)
    left = s + 1
    right = s * 10
    join = Computed(lambda: calls.append(1) or left.value + right.value)
    assert join.value == 12
    s.value = 2
    assert join.value == 23
    assert len(calls) == 2


def test_dynamic_dependencies_drop_unread_branch():
    calls = []
    flag = Signal(True)
    a = Signal("a")
    b = Signal("b")
    c = Computed(lambda: calls.append(1) or (a.value if flag.value else b.value))
    assert c.value == "a"
    flag.value = False
    assert c.value == "b"
    a.value = "A"  # no longer a dependency
    assert c.value == "b"
    assert len(calls) == 2
    assert a._observer_count() == 0


def test_equal_scalar_result_stops_propagation():
    calls = []
    s = Signal(2)
    parity = s % 2
    downstream = Computed(lambda: calls.append(1) or parity.value + 100)
    assert downstream.value == 100
    s.value = 4  # parity unchanged
    assert downstream.value == 100
    assert len(calls) == 1


def test_nan_to_nan_is_not_a_change():
    calls = []
    s = Signal(math.nan)
    c = Computed(lambda: calls.append(1) or s.value)
    c.value
    s.value = float("nan")
    c.value
    assert len(calls) == 1


def test_errors_are_cached_and_recover():
    calls = []
    s = Signal(0)

    def divide():
        calls.append(1)
        return 10 // s.value

    c = Computed(divide)
    with pytest.raises(ZeroDivisionError):
        c.value
    with pytest.raises(ZeroDivisionError):
        c.value
    assert len(calls) == 1  # the failure is cached
    s.value = 5  # read before the failure, so still a dependency
    assert c.value == 2


def test_base_exception_is_not_cached():
    attempts = []
    s = Signal(1)

    def interrupt_once():
        attempts.append(1)
        value = s.value
        if len(attempts) == 1:
            raise KeyboardInterrupt
        return value

    c = Computed(interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        c.value
    assert c.value == 1
    assert len(attempts) == 2


def test_cycle_is_detected():
    holder = {}
    a = Computed(lambda: holder["b"].value + 1)
    holder["b"] = Computed(lambda: a.value + 1)
    with pytest.raises(RuntimeError, match="Cycle detected"):
        a.value


def test_untracked_read_does_not_subscribe():
    calls = []
    tracked = Signal(1)
    hidden = Signal(10)

    def compute():
        calls.append(1)
        with untracked():
            extra = hidden.value
        return tracked.value + extra

    c = Computed(compute)
    assert c.value == 11
    hidden.value = 20
    assert c.value == 11
    assert len(calls) == 1
    tracked.value = 2
    assert c.value == 22


def test_numpy_values_change_by_identity():
    np = pytest.importorskip("numpy")
    calls = []
    first = np.array([1.0, 2.0])
    s = Signal(first)
    total = Computed(lambda: calls.append(1) or float(s.value.sum()))
    assert total.value == 3.0
    s.value = first  # same object: unchanged
    assert total.value == 3.0
    s.value = np.array([1.0, 2.0])  # equal contents, new object: changed
    assert total.value == 3.0
    assert len(calls) == 2
    scaled = s * 2  # operator node over an ndarray
    assert scaled.value.tolist() == [2.0, 4.0]
