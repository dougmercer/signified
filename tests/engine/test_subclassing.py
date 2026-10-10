"""Python-side customization that a native fast path must not bypass."""

from signified import Computed, Signal


def test_subclass_value_override_is_used_by_operators():
    class CountingSignal(Signal):
        reads = 0

        @property
        def value(self):
            type(self).reads += 1
            return super().value

        @value.setter
        def value(self, new):
            super(CountingSignal, type(self)).value.__set__(self, new)

    source = CountingSignal(1)
    out = source + 1
    assert out.value == 2
    assert CountingSignal.reads >= 1


def test_subclass_instances_keep_reactive_behavior():
    class Named(Signal):
        __slots__ = ()

    s = Named(3)
    doubled = s * 2
    assert doubled.value == 6
    s.value = 4
    assert doubled.value == 8


def test_runtime_generic_subscription():
    assert Signal[int] is not None
    assert Computed[int] is not None


def test_attribute_proxy_and_forwarded_writes():
    class Box:
        def __init__(self, size):
            self.size = size

    s = Signal(Box(1))
    size = s.size
    assert size.value == 1
    s.size = 5  # forwarded to the wrapped object, then notifies
    assert size.value == 5


def test_signal_subclass_notify_and_update_overrides_run():
    calls = []

    class Logged(Signal):
        def notify(self):
            calls.append("notify")
            super().notify()

        def update(self):
            calls.append("update")
            super().update()

    class Box:
        def __init__(self):
            self.size = 0

    s = Logged(Box())
    size = s.size
    assert size.value == 0
    s.value = Box()
    assert calls == ["notify"]
    calls.clear()
    s.size = 5  # forwarded write
    assert calls == ["update", "notify"]
    assert size.value == 5
    calls.clear()
    s.invalidate()
    assert calls == ["update", "notify"]


def test_signal_subclass_notify_override_runs_when_at_restores():
    calls = []

    class Logged(Signal):
        def notify(self):
            calls.append("notify")
            super().notify()

    s = Logged(1)
    doubled = s * 2
    assert doubled.value == 2
    with s.at(5):
        assert doubled.value == 10
    assert calls == ["notify", "notify"]
    assert doubled.value == 2


def test_computed_subclass_notify_override_runs_on_invalidation():
    calls = []

    class Logged(Computed):
        def notify(self):
            calls.append("notify")
            super().notify()

    s = Signal(1)
    c = Logged(lambda: s.value + 1)
    downstream = c * 10
    assert downstream.value == 20
    s.value = 2
    assert calls == ["notify"]
    assert downstream.value == 30
    c.invalidate()
    assert calls == ["notify", "notify"]


def test_effect_subclass_update_override_runs_when_a_dependency_changes():
    from signified import Effect

    calls = []
    seen = []

    class Logged(Effect):
        def update(self):
            calls.append("update")
            super().update()

    s = Signal(1)
    effect = Logged(lambda: seen.append(s.value))
    s.value = 2
    assert calls == ["update"]
    assert seen == [1, 2]
    effect.dispose()
