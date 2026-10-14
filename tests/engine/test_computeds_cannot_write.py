"""A computed's function may not change a signal or notify observers.

A change made while a computed is being evaluated reaches dependents that
are halfway through their own evaluation or not yet subscribed, and left
some of them stuck on an old value. It raises instead, and the error is
cached like any other error from the function.
"""

from dataclasses import dataclass

import pytest

from signified import Computed, Effect, Signal, _core, computed, tracked_fields, untracked

CANNOT_WRITE = "while a Computed is being evaluated"


def test_assigning_a_signal_in_a_compute_raises_and_leaves_it_unchanged():
    log = Signal(0)
    s = Signal(1)

    def compute():
        log.value = log.value + 1
        return s.value * 2

    c = Computed(compute)
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        c.value
    assert log.value == 0


def test_the_error_is_cached_and_the_compute_recovers_when_it_stops_writing():
    target = Signal(0)
    writes = Signal(True)
    runs = []

    def compute():
        runs.append(1)
        if writes.value:
            target.value = 5
        return target.value

    c = Computed(compute)
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        c.value
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        c.value
    assert len(runs) == 1
    writes.value = False
    assert c.value == 0


def test_writing_the_value_a_signal_already_holds_is_allowed():
    s = Signal(3)
    c = Computed(lambda: (setattr(s, "value", 3), s.value)[1])
    assert c.value == 3


def test_signal_at_another_value_in_a_compute_raises():
    # The first case reported by key3d: downstream values froze at 1.
    s = Signal(0)

    def body():
        v = s.value
        with s.at(v + 100):
            pass
        return v

    x = Computed(body)
    y = computed(lambda v: v)(x)
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        y.value
    assert s.value == 0


@pytest.mark.parametrize("case", ["diamond", "other_signal", "branches"])
def test_reported_signal_at_cases_raise_instead_of_freezing(case):
    # The other three cases from key3d's report, which froze on 0.7.1.
    s = Signal(43)
    shift = Signal(0)
    src = computed(lambda v, sh: v + sh)(s, shift)

    def sample_at_45():
        with s.at(45):
            return src.value

    if case == "diamond":
        live = computed(lambda v: v)(src)
        reader = computed(lambda a, z: a - z)(live, Computed(sample_at_45))
    elif case == "other_signal":
        reader = computed(lambda v: v)(Computed(sample_at_45))
    else:
        reader = Computed(lambda: src.value if s.value >= 45 else sample_at_45())
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        reader.value
    assert s.value == 43


def test_signal_at_the_current_value_is_allowed_in_a_compute():
    frame = Signal(10)
    position = computed(lambda f: f * 2)(frame)

    def compute():
        with frame.at(frame.value):
            return position.value

    c = Computed(compute)
    assert c.value == 20
    frame.value = 11
    assert c.value == 22


def test_writes_inside_untracked_in_a_compute_raise():
    s = Signal(0)

    def compute():
        with untracked():
            s.value = 1
        return 0

    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        Computed(compute).value


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(),
        lambda s: s.invalidate(),
        lambda s: s._notify(),
        lambda s: s.__setitem__(0, 9),
    ],
    ids=["update", "invalidate", "notify", "item assignment"],
)
def test_notifying_a_signals_observers_in_a_compute_raises(change):
    s = Signal([1])
    total = computed(sum)(s)
    assert total.value == 1

    def compute():
        change(s)
        return 0

    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        Computed(compute).value


@pytest.mark.parametrize(
    "change",
    [lambda c: c.update(), lambda c: c._invalidate(), lambda c: c._notify()],
    ids=["update", "invalidate", "notify"],
)
def test_invalidating_another_computed_in_a_compute_raises(change):
    s = Signal(1)
    other = computed(lambda v: v + 1)(s)
    reader = computed(lambda v: v)(other)
    assert reader.value == 2

    def compute():
        change(other)
        return 0

    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        Computed(compute).value


def test_assigning_a_tracked_field_in_a_compute_raises():
    @tracked_fields
    @dataclass(slots=True)
    class Box:
        size: int = 1

    box = Box()
    area = Computed(lambda: box.size * box.size)
    assert area.value == 1

    def compute():
        box.size = 2
        return 0

    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        Computed(compute).value
    assert area.value == 1


def test_a_custom_equal_cannot_change_a_signal():
    s = Signal(1)
    other = Signal(0)

    def equal(previous, current):
        other.value = other.value + 1
        return False

    c = Computed(lambda: [s.value], equal=equal)
    assert c.value == [1]
    s.value = 2
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        c.value
    assert other.value == 0


def test_an_effect_created_in_a_compute_cannot_change_a_signal():
    s = Signal(0)

    def compute():
        Effect(lambda: setattr(s, "value", 1))
        return 0

    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        Computed(compute).value
    assert s.value == 0


def test_effects_may_change_signals():
    source = Signal(1)
    doubled = computed(lambda v: v * 2)(source)
    mirror = Signal(0)
    effect = Effect(lambda: setattr(mirror, "value", doubled.value))
    assert mirror.value == 2
    source.value = 5
    assert mirror.value == 10
    effect.dispose()


class _WritingHook:
    def __init__(self, write):
        self.write = write

    def created(self, *, value):
        pass

    def read(self, *, value):
        pass

    def updated(self, *, value):
        self.write(value)


def test_an_updated_hook_cannot_change_a_signal_while_a_reader_checks_its_dependencies(monkeypatch):
    s = Signal(1)
    shift = Signal(0)
    x = computed(lambda v: v * 10)(s)
    y = computed(lambda v, sh: v + sh)(x, shift)
    assert y.value == 10

    def write(value):
        if value is x:
            shift.value = shift.value + 1

    monkeypatch.setattr(_core.config, "hooks", _WritingHook(write))
    s.value = 2
    with pytest.raises(RuntimeError, match=CANNOT_WRITE):
        y.value
    monkeypatch.setattr(_core.config, "hooks", None)
    assert shift.value == 0
