"""Performance benchmarks for signified reactive primitives."""

from signified import Computed, Signal, computed, deep_unref, effect, unref

# ---------------------------------------------------------------------------
# Signal creation and value access
# ---------------------------------------------------------------------------


def test_bench_signal_create(benchmark):
    """Benchmark creating a Signal."""
    benchmark(Signal, 42)


def test_bench_signal_read(benchmark):
    """Benchmark reading a Signal value."""
    s = Signal(42)
    benchmark(lambda: s.value)


def test_bench_signal_write(benchmark):
    """Benchmark writing a new value to a Signal."""
    s = Signal(0)
    i = 0

    def write():
        nonlocal i
        i += 1
        s.value = i

    benchmark(write)


# ---------------------------------------------------------------------------
# Computed creation and evaluation
# ---------------------------------------------------------------------------


def test_bench_computed_create(benchmark):
    """Benchmark creating a Computed that depends on a Signal."""
    s = Signal(10)
    benchmark(lambda: Computed(lambda: s.value * 2))


def test_bench_computed_read(benchmark):
    """Benchmark reading a Computed value (already evaluated)."""
    s = Signal(10)
    c = Computed(lambda: s.value * 2)
    _ = c.value  # force initial evaluation
    benchmark(lambda: c.value)


def test_bench_computed_propagation(benchmark):
    """Benchmark Signal write that propagates through a Computed."""
    s = Signal(0)
    c = Computed(lambda: s.value + 1)
    _ = c.value  # force initial evaluation
    i = 0

    def propagate():
        nonlocal i
        i += 1
        s.value = i
        return c.value

    benchmark(propagate)


# ---------------------------------------------------------------------------
# Dependency chains
# ---------------------------------------------------------------------------


def test_bench_chain_propagation(benchmark):
    """Benchmark propagation through a chain of 10 Computed nodes."""
    s = Signal(0)
    chain = [s]
    for _ in range(10):
        prev = chain[-1]
        chain.append(Computed(lambda prev=prev: prev.value + 1))
    tail = chain[-1]
    _ = tail.value  # force evaluation of the full chain
    i = 0

    def propagate_chain():
        nonlocal i
        i += 1
        s.value = i
        return tail.value

    benchmark(propagate_chain)


# ---------------------------------------------------------------------------
# Fan-out (diamond) dependency graphs
# ---------------------------------------------------------------------------


def test_bench_fan_out(benchmark):
    """Benchmark propagation with fan-out: one Signal observed by 10 Computeds."""
    s = Signal(0)
    dependents = [Computed(lambda i=i: s.value + i) for i in range(10)]
    for d in dependents:
        _ = d.value
    i = 0

    def propagate_fan():
        nonlocal i
        i += 1
        s.value = i
        return [d.value for d in dependents]

    benchmark(propagate_fan)


# ---------------------------------------------------------------------------
# Nested Signals and unref
# ---------------------------------------------------------------------------


def test_bench_nested_signal_read(benchmark):
    """Benchmark reading through nested Signals (3 levels)."""
    inner = Signal(7)
    mid = Signal(inner)
    outer = Signal(mid)
    benchmark(lambda: outer.value)


def test_bench_unref(benchmark):
    """Benchmark unref on a nested Signal."""
    inner = Signal(99)
    outer = Signal(inner)
    benchmark(unref, outer)


def test_bench_deep_unref_dict(benchmark):
    """Benchmark deep_unref on a dict containing reactive values."""
    payload = {"a": Signal(1), "b": [Signal(2), Signal(3)], "c": {"d": Signal(4)}}
    benchmark(deep_unref, payload)


# ---------------------------------------------------------------------------
# @computed decorator
# ---------------------------------------------------------------------------


def test_bench_computed_decorator(benchmark):
    """Benchmark calling a @computed-decorated function."""

    @computed
    def add(x, y):
        return x + y

    a = Signal(1)
    b = Signal(2)
    benchmark(lambda: add(a, b).value)


# ---------------------------------------------------------------------------
# Effect
# ---------------------------------------------------------------------------


def test_bench_effect_creation(benchmark):
    """Benchmark creating an Effect that observes a Signal."""
    s = Signal(0)

    def create_effect():
        e = effect(lambda x: None)(s)
        e.dispose()

    benchmark(create_effect)


# ---------------------------------------------------------------------------
# Operator overloads (arithmetic via _ReactiveMixIn)
# ---------------------------------------------------------------------------


def test_bench_operator_chain(benchmark):
    """Benchmark chained arithmetic operators producing Computed values."""
    a = Signal(2)
    b = Signal(3)

    def chain_ops():
        result = a + b * a - b
        return result.value

    benchmark(chain_ops)
