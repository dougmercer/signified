import pytest

from signified import Computed, Signal, computed


def test_computed_basic():
    """Test basic Computed functionality."""
    s = Signal(5)
    c = Computed(lambda: s.value * 2, dependencies=[s])

    assert c.value == 10

    s.value = 7
    assert c.value == 14


def test_computed_decorator():
    """Test the @computed decorator."""
    s = Signal(5)

    @computed
    def double_it(x):
        return x * 2

    c = double_it(s)
    assert c.value == 10

    s.value = 7
    assert c.value == 14


def test_computed_dependencies():
    """Test Computed with multiple dependencies."""
    s1 = Signal(5)
    s2 = Signal(10)

    @computed
    def add_em(a, b):
        return a + b

    c = add_em(s1, s2)
    assert c.value == 15

    s1.value = 7
    assert c.value == 17

    s2.value = 13
    assert c.value == 20


def test_computed_with_nested_signals():
    """Test Computed with multiple nested Signals."""
    s1 = Signal(Signal(5))
    s2 = Signal(Signal(Signal(3)))

    @computed
    def complex_computation(a, b):
        return a * b

    result = complex_computation(s1, s2)
    assert result.value == 15

    s1.value = 7
    assert result.value == 21


def test_computed_chaining():
    """Test chaining of Computed values."""
    s = Signal(5)
    c1 = computed(lambda x: x * 2)(s)
    c2 = computed(lambda x: x + 3)(c1)

    assert c2.value == 13
    s.value = 10
    assert c2.value == 23


def test_computed_container_with_reactive_values():
    s = [1, Signal(2), Signal(3)]
    result = computed(sum)(s)
    assert result.value == 6
    s[-1].value = 10
    assert result.value == 13


def test_computed_container_with_deeply_nestedreactive_values():
    def flatten(lst):
        result = []
        for item in lst:
            if isinstance(item, list):
                result.extend(flatten(item))
            else:
                result.append(item)
        return result

    s = [1, [Signal(2), Signal([Signal(3), Signal([4, Signal(5)])])], Signal(6)]
    result = computed(flatten)(s)
    assert result.value == [1, 2, 3, 4, 5, 6]
    s[1][0].value = 10
    assert result.value == [1, 10, 3, 4, 5, 6]


def test_computed_is_lazy_until_read():
    source = Signal(2)
    reads: list[int] = []

    derived = Computed(lambda: reads.append(source.value) or source.value * 10)

    assert reads == []
    assert derived.value == 20
    assert reads == [2]

    source.value = 3
    assert reads == [2]
    assert derived.value == 30
    assert reads == [2, 3]


def test_computed_dynamic_dependency_branch_switching():
    use_left = Signal(True)
    left = Signal(1)
    right = Signal(10)

    selected = Computed(lambda: left.value if use_left.value else right.value)

    assert selected.value == 1

    right.value = 20
    assert selected.value == 1

    use_left.value = False
    assert selected.value == 20

    left.value = 2
    assert selected.value == 20

    right.value = 30
    assert selected.value == 30


def test_computed_skips_downstream_recompute_when_upstream_value_stable():
    source = Signal(1)
    upstream_runs = 0
    downstream_runs = 0

    def upstream_fn() -> int:
        nonlocal upstream_runs
        upstream_runs += 1
        return source.value % 2

    upstream = Computed(upstream_fn)

    def downstream_fn() -> int:
        nonlocal downstream_runs
        downstream_runs += 1
        return upstream.value * 10

    downstream = Computed(downstream_fn)

    assert downstream.value == 10
    assert upstream_runs == 1
    assert downstream_runs == 1

    source.value = 3  # upstream stays 1, so downstream should skip recompute.
    assert downstream.value == 10
    assert upstream_runs == 2
    assert downstream_runs == 1


def test_computed_dependencies_argument_is_deprecated_and_ignored():
    source = Signal(1)
    unrelated = Signal(10)

    with pytest.warns(DeprecationWarning, match=r"Computed\(\.\.\., dependencies=.*\)"):
        derived = Computed(lambda: source.value + 1, dependencies=[unrelated])

    calls = 0
    original_update = derived.update

    def wrapped_update() -> None:
        nonlocal calls
        calls += 1
        original_update()

    derived.update = wrapped_update  # type: ignore[method-assign]
    unrelated.value = 11

    assert calls == 0
    assert derived.value == 2


def test_nested_signal_change_invalidates_computed_once():
    inner = Signal(1)
    outer = Signal(inner)
    derived = Computed(lambda: outer.value + 1)
    _ = derived.value

    calls = 0
    original_update = derived.update

    def wrapped_update() -> None:
        nonlocal calls
        calls += 1
        original_update()

    derived.update = wrapped_update  # type: ignore[method-assign]
    inner.value = 2

    assert calls == 1
    assert derived.value == 3
