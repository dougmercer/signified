"""Performance benchmarks for signified reactive primitives."""

import pytest

from signified import Computed, Effect, Signal, computed, deep_unref, effect, unref

pytestmark = pytest.mark.benchmark
slow_benchmark = pytest.mark.slow_benchmark

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


def test_bench_signal_update(benchmark):
    """Benchmark forcing notification after mutating a contained object."""
    payload = {"count": 0}
    s = Signal(payload)

    def mutate():
        payload["count"] += 1
        s.update()
        return payload["count"]

    benchmark(mutate)


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


def test_bench_computed_invalidate(benchmark):
    """Benchmark forced recomputation after rewiring a non-reactive container."""

    class Holder:
        def __init__(self, sig):
            self.sig = sig

    left = Signal(1)
    right = Signal(2)
    holder = Holder(left)
    derived = Computed(lambda: holder.sig.value * 2)
    _ = derived.value

    def invalidate():
        holder.sig = right if holder.sig is left else left
        derived.invalidate()
        return derived.value

    benchmark(invalidate)


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


# ---------------------------------------------------------------------------
# Larger steady-state workloads
# ---------------------------------------------------------------------------


@slow_benchmark
def test_bench_deep_chain_updates(benchmark):
    """Benchmark repeated updates through a longer computed chain."""
    source = Signal(0)
    sink = source
    for _ in range(24):
        sink = sink + 1
    _ = sink.value

    def propagate_chain():
        checksum = 0
        for i in range(1, 3_001):
            source.value = i
            checksum += sink.value
        return checksum

    benchmark(propagate_chain)


@slow_benchmark
def test_bench_fanout_updates(benchmark):
    """Benchmark one source update invalidating many downstream nodes."""
    source = Signal(0)
    leaves = [source + offset for offset in range(64)]
    sink = computed(sum)(leaves)
    _ = sink.value

    def propagate_fanout():
        checksum = 0
        for i in range(1, 1_501):
            source.value = i
            checksum += sink.value
        return checksum

    benchmark(propagate_fanout)


@slow_benchmark
def test_bench_diamond_updates(benchmark):
    """Benchmark a branch-and-merge graph under repeated updates."""
    source = Signal(0)
    left = [source * factor for factor in range(1, 25)]
    right = [source + bias for bias in range(24)]
    merged = [lhs - rhs for lhs, rhs in zip(left, right, strict=True)]
    sink = computed(sum)(merged)
    _ = sink.value

    def propagate_diamond():
        checksum = 0
        for i in range(1, 1_501):
            source.value = i
            checksum += sink.value
        return checksum

    benchmark(propagate_diamond)


@slow_benchmark
def test_bench_animation_stack(benchmark):
    """Benchmark a frame-driven animation-style workload."""
    frame = Signal(0)
    clamp_ease = computed(lambda start, end, f: max(0.0, min(1.0, (f - start) / max(end - start, 1))))
    apply_step = computed(lambda value, ease, delta: value + ease * delta)

    leaves = []
    for i in range(12):
        value = Signal(float(i))
        for j in range(3):
            offset = i * 3 + j
            ease = clamp_ease(offset * 4, offset * 4 + 24, frame)
            value = apply_step(value, ease, float(j + 1))
        leaves.append(value)

    sink = computed(sum)(leaves)
    _ = sink.value

    def animate():
        checksum = 0.0
        for i in range(1_500):
            frame.value = i % 120
            checksum += sink.value
        return int(checksum)

    benchmark(animate)


@slow_benchmark
def test_bench_multi_input_computed(benchmark):
    """Benchmark a computed with several inputs updating at different rates."""
    pos_x = Signal(0.0)
    pos_y = Signal(0.0)
    pos_z = Signal(5.0)
    radius = Signal(5.0)
    horizontal = Signal(0.0)
    vertical = Signal(0.3)

    result = computed(lambda x, y, z, r, h, v: x + y + z + r * h + r * v)(
        pos_x,
        pos_y,
        pos_z,
        radius,
        horizontal,
        vertical,
    )
    _ = result.value

    def update_inputs():
        checksum = 0.0
        for i in range(5_000):
            horizontal.value = (i % 60) * 0.01
            if i % 3 == 0:
                vertical.value = (i // 3 % 30) * 0.005
            if i % 10 == 0:
                radius.value = 5.0 + (i // 10 % 5)
            if i % 30 == 0:
                pos_x.value = float(i % 5)
            checksum += result.value
        return int(checksum)

    benchmark(update_inputs)


@slow_benchmark
def test_bench_computed_signal_at(benchmark):
    """Benchmark repeated scoped overrides through Signal.at()."""
    left = Signal(1)
    right = Signal(2)
    bias = Signal(3)
    subtotal = left * 2 + right
    total = subtotal + bias * 3
    _ = total.value

    def scoped_override():
        checksum = 0
        for i in range(1, 3_001):
            with left.at(i), right.at(i + 1), bias.at(i & 7):
                checksum += total.value
        return checksum

    benchmark(scoped_override)


@slow_benchmark
def test_bench_shared_clock_reads(benchmark):
    """Benchmark shared invalidation followed by repeated partial reads."""
    clock = Signal(0)
    bases = [Signal(i) for i in range(32)]
    affine_step = computed(lambda value, scale, offset: value * scale + offset)
    mix_pair = computed(lambda left, right, bias: left + right + bias)

    leaves = []
    for index, base in enumerate(bases):
        staged = affine_step(clock, (index % 3) + 1, index)
        leaves.append(mix_pair(staged, base, index % 5))
    _ = [leaf.value for leaf in leaves]

    def tick():
        checksum = 0
        for i in range(1, 1_201):
            clock.value = i
            bases[i % 32].value = i * 2
            start = (i * 8) % 32
            for offset in range(8):
                checksum += leaves[(start + offset) % 32].value
        return checksum

    benchmark(tick)


@slow_benchmark
def test_bench_subscription_churn(benchmark):
    """Benchmark repeated subscribe and unsubscribe cycles."""
    source = Signal(0)
    observers = [source + offset for offset in range(48)]
    sink = computed(sum)(observers)
    _ = sink.value

    def churn():
        checksum = 0
        for _ in range(250):
            for observer in observers:
                source.unsubscribe(observer)
            for observer in observers:
                source.subscribe(observer)
            source.value = source.value + 1
            checksum += sink.value
        return checksum

    benchmark(churn)


@slow_benchmark
def test_bench_stacked_layers(benchmark):
    """Benchmark repeated reads through a deep layered graph."""
    source = Signal(1)
    driver = Signal(0)
    affine_step = computed(lambda value, scale, offset: value * scale + offset)

    node = source
    for index in range(14):
        step = affine_step(node, (index % 3) + 1, index)
        node = step + driver + (index % 7)

    tail = node - source
    summary = tail + driver + 14
    _ = summary.value

    def update_layers():
        checksum = 0
        for i in range(1, 2_201):
            driver.value = i
            source.value = (i % 11) + 1
            checksum += summary.value
            checksum += tail.value
        return checksum

    benchmark(update_layers)


@slow_benchmark
def test_bench_scoped_context_reads(benchmark):
    """Benchmark several downstream reads inside Signal.at() scopes."""
    left = Signal(1)
    right = Signal(2)
    selector = Signal(0)
    bias = Signal(3)
    affine_step = computed(lambda value, scale, offset: value * scale + offset)

    primary = left + right + 1
    selected = affine_step(selector, 3, 2)
    merged = primary + selected + 4
    total = merged + bias + 5
    _ = total.value

    def scoped_reads():
        checksum = 0
        for i in range(1, 2_201):
            with selector.at(i), left.at(i + 1), right.at(i + 2), bias.at(i & 7):
                checksum += primary.value + merged.value + total.value
        return checksum

    benchmark(scoped_reads)


@slow_benchmark
def test_bench_dynamic_dependency_switch(benchmark):
    """Benchmark per-update dependency switching."""
    selector = Signal(0)
    branches = [Signal(i) for i in range(128)]
    active_value = computed(lambda selected: branches[selected].value)
    active = active_value(selector)
    sink = active * 2 + selector
    _ = sink.value

    def switch_dependencies():
        checksum = 0
        for i in range(1, 4_001):
            idx = i % 128
            selector.value = idx
            branches[idx].value = i
            checksum += sink.value
        return checksum

    benchmark(switch_dependencies)


@slow_benchmark
def test_bench_shared_dependency_branches(benchmark):
    """Benchmark branches that share an intermediate computed node."""
    left = Signal(1)
    right = Signal(2)
    selector = Signal(0)
    affine_step = computed(lambda value, scale, offset: value * scale + offset)

    shared = left + right + 3
    branch_a = affine_step(shared, 2, 1)
    branch_b = shared + selector + 2
    branch_c = branch_a - selector
    combined = branch_b + branch_c + 4
    _ = combined.value

    def update_shared_graph():
        checksum = 0
        for i in range(1, 1_801):
            selector.value = i
            left.value = (i % 13) + 1
            right.value = (i % 17) + 2
            checksum += branch_b.value + branch_c.value + combined.value
        return checksum

    benchmark(update_shared_graph)


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


@slow_benchmark
def test_bench_effect_fanout_updates(benchmark):
    """Benchmark many eager effects subscribed to one source."""
    source = Signal(0)
    accumulator = [0]
    effects = [
        Effect(
            lambda source=source, offset=offset, accumulator=accumulator: accumulator.__setitem__(
                0,
                accumulator[0] + source.value + offset,
            )
        )
        for offset in range(192)
    ]
    _ = len(effects)

    def update_effects():
        baseline = accumulator[0]
        for i in range(1, 1_501):
            source.value = i
        return accumulator[0] - baseline

    benchmark(update_effects)


# ---------------------------------------------------------------------------
# Construction workloads
# ---------------------------------------------------------------------------


@slow_benchmark
def test_bench_build_deep_chain(benchmark):
    """Benchmark constructing a deeper computed chain."""

    def build_chain():
        source = Signal(0)
        sink = source
        for _ in range(160):
            sink = sink + 1
        return sink.value

    benchmark(build_chain)


@slow_benchmark
def test_bench_build_fanout_graph(benchmark):
    """Benchmark constructing a wider fan-out graph."""

    def build_fanout():
        source = Signal(0)
        leaves = [source + offset for offset in range(256)]
        sink = computed(sum)(leaves)
        return sink.value

    benchmark(build_fanout)


@slow_benchmark
def test_bench_build_diamond_graph(benchmark):
    """Benchmark constructing a wider branch-and-merge graph."""

    def build_diamond():
        source = Signal(1)
        left = [source * factor for factor in range(1, 193)]
        right = [source + bias for bias in range(192)]
        merged = [lhs - rhs for lhs, rhs in zip(left, right, strict=True)]
        sink = computed(sum)(merged)
        return sink.value

    benchmark(build_diamond)
