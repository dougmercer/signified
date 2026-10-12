"""signified_api_example: computeds evaluated by a Rust kernel in another extension module."""

import gc
import subprocess
import sys

import pytest

from signified import Computed, Effect, Signal

example = pytest.importorskip("signified_api_example")


def test_values_are_computed_from_resolved_arguments():
    a, b = Signal(1.0), Signal(2.0)
    total = example.weighted_sum([2.0, 3.0, 1.0], a, b, 0.5)
    assert isinstance(total, Computed)
    assert total.value == 8.5
    a.value = 4.0
    assert total.value == 14.5


def test_python_computeds_and_effects_follow_native_ones():
    a = Signal(1.0)
    total = example.weighted_sum([10.0], a)
    doubled = Computed(lambda: total.value * 2)
    seen = []
    effect = Effect(lambda: seen.append(doubled.value))
    a.value = 2.0
    assert doubled.value == 40.0
    assert seen == [20.0, 40.0]
    del effect


def test_an_equal_value_keeps_readers_current():
    a, b = Signal(1.0), Signal(2.0)
    total = example.weighted_sum([1.0, 1.0], a, b)
    runs = []
    reader = Computed(lambda: runs.append(total.value) or total.value)
    assert reader.value == 3.0
    version = total._version
    a.value, b.value = 2.0, 1.0
    assert reader.value == 3.0
    assert total._version == version
    assert runs == [3.0]


def test_errors_are_raised_to_readers_and_recovered_from():
    a = Signal(1.0)
    total = example.weighted_sum([1.0], a)
    a.value = "one"
    with pytest.raises(TypeError, match="expected a number"):
        total.value
    a.value = 5.0
    assert total.value == 5.0


def test_kernels_are_released_with_their_computeds():
    total = example.weighted_sum([1.0], Signal(1.0))
    total.value
    released = example.released()
    del total
    gc.collect()
    assert example.released() == released + 1


def test_the_interpreter_exits_cleanly_with_live_computeds():
    # Computeds still alive at exit are released while the interpreter finalizes.
    script = (
        "import signified, signified_api_example as e\n"
        "keep = [e.weighted_sum([1.0], signified.Signal(float(i))) for i in range(10)]\n"
        "print(sum(c.value for c in keep))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "45.0"
