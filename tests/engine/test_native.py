"""Native computeds: values computed by a kernel from another extension, through the C API.

`signified._core._native_test_sum` makes one through the `_C_API` capsule, as another extension
would, with a kernel that sums its arguments and reports an equal sum as unchanged.
"""

import gc

import pytest

from signified import Computed, Signal, _core
from signified._core import _native_test_counts, _native_test_sum


def test_the_capsule_is_exported():
    assert type(_core._C_API).__name__ == "PyCapsule"
    assert "signified._core._C_API" in repr(_core._C_API)


def test_reactive_arguments_are_resolved_and_tracked():
    a, b = Signal(1.0), Signal(2.0)
    total = _native_test_sum(Computed, a, b, 0.5)
    assert isinstance(total, Computed)
    assert total.value == 3.5
    a.value = 10.0
    assert total.value == 12.5
    assert [dep is a or dep is b for dep in total._deps] == [True, True]


def test_kernels_run_lazily_once_per_change():
    a = Signal(1.0)
    total = _native_test_sum(Computed, a)
    runs = _native_test_counts()[0]
    total.value
    total.value
    assert _native_test_counts()[0] == runs + 1
    a.value = 2.0
    a.value = 3.0
    assert total.value == 3.0
    assert _native_test_counts()[0] == runs + 2


def test_returning_the_previous_value_keeps_readers_current():
    a, b = Signal(1.0), Signal(2.0)
    total = _native_test_sum(Computed, a, b)
    seen = []
    reader = Computed(lambda: seen.append(total.value) or total.value)
    assert reader.value == 3.0
    first, version = total.value, total._version
    a.value, b.value = 2.0, 1.0  # the same sum
    assert reader.value == 3.0
    assert total.value is first
    assert total._version == version
    assert seen == [3.0]


def test_kernel_errors_are_cached_and_recovered_from():
    a = Signal(1.0)
    total = _native_test_sum(Computed, a)
    assert total.value == 1.0
    a.value = "not a number"
    with pytest.raises(TypeError):
        total.value
    with pytest.raises(TypeError):
        total.value
    a.value = 4.0
    assert total.value == 4.0


def test_native_computeds_feed_python_computeds_and_effects():
    a = Signal(1.0)
    total = _native_test_sum(Computed, a, 1.0)
    doubled = Computed(lambda: total.value * 2)
    assert doubled.value == 4.0
    a.value = 5.0
    assert doubled.value == 12.0


def test_subclasses_and_the_wrong_class():
    class Named(Computed):
        pass

    assert isinstance(_native_test_sum(Named, 1.0), Named)
    released = _native_test_counts()[1]
    with pytest.raises(TypeError):
        _native_test_sum(Signal, 1.0)
    # The kernel's context is released even though no computed was made.
    assert _native_test_counts()[1] == released + 1


def test_the_context_is_released_with_the_computed():
    a = Signal(1.0)
    total = _native_test_sum(Computed, a)
    total.value
    released = _native_test_counts()[1]
    del total
    gc.collect()
    assert _native_test_counts()[1] == released + 1
