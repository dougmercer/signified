"""signified.sample(): a value as if a signal held another value."""

import pytest

from signified import Binding, Computed, Signal, batch, computed, sample, untracked
from signified._core import _native_test_sum


def counting(fn, calls):
    def counted(*args):
        calls.append(args)
        return fn(*args)

    return counted


def test_reads_the_value_as_if_the_signal_held_another_value():
    frame = Signal(10)
    position = computed(lambda f: f * 2)(frame)
    assert sample(position, frame, 45).value == 90
    assert frame.value == 10


def test_reading_a_sample_leaves_the_live_graph_untouched():
    frame = Signal(10)
    calls = []
    position = computed(counting(lambda f: f * 2, calls))(frame)
    assert position.value == 20
    version = position._version

    assert sample(position, frame, 45).value == 90
    assert position._version == version
    assert position._value == 20
    calls.clear()
    assert position.value == 20
    assert calls == []


def test_changing_only_the_sampled_signal_runs_nothing():
    frame = Signal(0)
    calls = []
    position = computed(counting(lambda f: f * 2, calls))(frame)
    held = computed(counting(lambda p: p + 1, calls))(sample(position, frame, 45))
    assert held.value == 91
    calls.clear()
    for f in range(1, 6):
        frame.value = f
        assert held.value == 91
    assert calls == []


def test_another_input_changing_updates_the_sample_and_its_readers():
    frame = Signal(0)
    shift = Signal(0)
    source = computed(lambda f, sh: f + sh)(frame, shift)
    reader = computed(lambda v: v)(sample(source, frame, 45))
    for f in (0, 10, 50):
        frame.value = f
        assert reader.value == 45
    shift.value = 5
    frame.value = 10
    assert reader.value == 50


def test_a_reactive_at_is_read_with_the_signals_real_value():
    frame = Signal(0)
    position = computed(lambda f: f * 10)(frame)
    until = sample(position, frame, computed(lambda f: min(f, 3))(frame))
    after = sample(position, frame, computed(lambda f: max(f, 3))(frame))
    delay = sample(position, frame, frame - 2)
    for f in range(7):
        frame.value = f
        assert until.value == min(f, 3) * 10
        assert after.value == max(f, 3) * 10
        assert delay.value == (f - 2) * 10


def test_live_and_sampled_reads_run_each_live_function_once_per_frame():
    frame = Signal(0)
    calls = []
    position = computed(counting(lambda f: f * 10, calls))(frame)
    until = sample(position, frame, computed(lambda f: min(f, 3))(frame))
    after = sample(position, frame, computed(lambda f: max(f, 3))(frame))
    for f in range(7):
        frame.value = f
        calls.clear()
        for read in ([position, until, after], [after, until, position])[f % 2]:
            read.value
        # Live once per frame; at most one more while a sample is frozen
        # and its result is not cached yet.
        assert calls.count((f,)) == 1
        assert len(calls) <= 2


def test_leaving_the_sampled_value_is_noticed_even_if_the_live_value_is_unchanged():
    frame = Signal(45)
    other = Signal(0)
    total = computed(lambda f, o: f + o)(frame, other)
    held = sample(total, frame, 45)
    assert held.value == 45
    with batch():
        frame.value = 46
        other.value = -1
    assert total.value == 45
    assert held.value == 44


def test_values_that_do_not_depend_on_the_signal_come_from_the_live_graph():
    frame = Signal(0)
    size = Signal(2)
    calls = []
    mesh = computed(counting(lambda s: [s] * 3, calls))(size)
    placed = computed(lambda f, m: (f, len(m)))(frame, mesh)
    assert placed.value == (0, 3)
    calls.clear()
    assert sample(placed, frame, 45).value == (45, 3)
    assert calls == []


def test_a_live_value_that_starts_depending_on_the_signal_is_noticed():
    branch = Signal(False)
    frame = Signal(0)
    other = Signal(7)
    pick = Computed(lambda: frame.value if branch.value else other.value)
    assert pick.value == 7
    held = sample(pick, frame, 45)
    assert held.value == 7
    with batch():
        branch.value = True
        frame.value = 7
    assert pick.value == 7
    assert held.value == 45


def test_invalidating_a_sampled_computed_updates_the_sample_and_its_readers():
    s = Signal(1)
    external = [1]
    total = Computed(lambda: s.value + external[0])
    reader = computed(lambda v: v)(sample(total, s, 7))
    assert reader.value == 8
    external[0] = 2
    total.invalidate()
    assert reader.value == 9
    assert total.value == 3


def test_every_invalidation_of_a_sampled_computed_reaches_the_sample():
    s = Signal(1)
    external = [1]
    total = Computed(lambda: s.value + external[0])
    held = sample(total, s, 7)
    seen = [held.value]
    for value in (2, 3):
        external[0] = value
        total.invalidate()
        seen.append(held.value)
    assert seen == [8, 9, 10]


def test_sampling_computeds_that_read_each_other_raises_the_cycle_error():
    a = Computed(lambda: b.value)
    b = Computed(lambda: a.value)
    with pytest.raises(RuntimeError, match="Cycle"):
        a.value
    with pytest.raises(RuntimeError, match="Cycle"):
        sample(a, Signal(0), 1).value


def test_invalidating_a_computed_under_the_sampled_value_updates_the_sample():
    s = Signal(1)
    external = [1]
    total = Computed(lambda: s.value + external[0])
    scaled = computed(lambda v: v * 10)(total)
    held = sample(scaled, s, 7)
    assert held.value == 80
    external[0] = 2
    total.invalidate()
    assert held.value == 90


def test_samples_of_samples():
    frame = Signal(0)
    position = computed(lambda f: f * 10)(frame)
    assert sample(sample(position, frame, 60), frame, 40).value == 600
    total = computed(lambda a, b: a + b)(sample(position, frame, 60), position)
    assert sample(total, frame, 40).value == 1000
    assert total.value == 600


def test_sampling_two_signals():
    a = Signal(0)
    b = Signal(0)
    both = computed(lambda x, y: (x, y))(a, b)
    assert sample(sample(both, a, 1), b, 2).value == (1, 2)
    assert sample(sample(both, a, 1), a, 2).value == (1, 0)


def test_branches_follow_the_sampled_value():
    frame = Signal(0)
    x = Signal("x")
    y = Signal("y")
    calls = []
    branch = Computed(counting(lambda: x.value if frame.value > 5 else y.value, calls))
    late = sample(branch, frame, 10)
    assert late.value == "x"
    calls.clear()
    y.value = "Y"
    assert late.value == "x"
    assert calls == []
    x.value = "X"
    assert late.value == "X"


def test_untracked_reads_see_the_sampled_value():
    frame = Signal(0)

    def peek():
        with untracked():
            return frame.value

    assert sample(Computed(peek), frame, 7).value == 7


def test_bindings_follow_the_sampled_value():
    frame = Signal(1)
    position = computed(lambda f: f * 2)(frame)
    assert sample(Binding(position), frame, 45).value == 90
    follows_frame = computed(lambda v: v + 1)(Binding(frame))
    assert sample(follows_frame, frame, 5).value == 6


def test_native_kernels_follow_the_sampled_value():
    frame = Signal(1.0)
    offset = Signal(0.5)
    total = _native_test_sum(Computed, frame, offset)
    assert total.value == 1.5
    late = sample(total, frame, 10.0)
    assert late.value == 10.5
    offset.value = 2.0
    assert late.value == 12.0
    assert total.value == 3.0


def test_plain_values_and_the_signal_itself():
    frame = Signal(0)
    assert sample(5, frame, 3).value == 5
    assert sample(frame, frame, 3).value == 3


def test_errors_surface_from_the_sample_and_it_recovers():
    frame = Signal(0)
    shift = Signal(0)
    ratio = computed(lambda f, sh: 1 / (f - 45 + sh))(frame, shift)
    late = sample(ratio, frame, 45)
    with pytest.raises(ZeroDivisionError):
        late.value
    with pytest.raises(ZeroDivisionError):
        late.value
    shift.value = 1
    assert late.value == 1.0
    assert ratio.value == pytest.approx(1 / -44)


def test_a_sample_that_reads_itself_is_a_cycle():
    frame = Signal(0)
    holder = []
    loops = Computed(lambda: frame.value + holder[0].value)
    late = sample(loops, frame, 3)
    holder.append(late)
    with pytest.raises(RuntimeError, match="Cycle"):
        late.value


def test_a_sampled_evaluation_cannot_change_signals():
    frame = Signal(0)
    other = Signal(0)

    def writes():
        other.value = frame.value
        return 0

    with pytest.raises(RuntimeError, match="while a Computed is being evaluated"):
        sample(Computed(writes), frame, 3).value
    assert other.value == 0


def test_the_signal_must_be_a_signal():
    frame = Signal(0)
    position = computed(lambda f: f * 2)(frame)
    with pytest.raises(TypeError, match="Signal"):
        sample(position, position, 1)  # type: ignore[arg-type]
