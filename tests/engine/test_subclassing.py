"""Python-side customization that a native fast path must not bypass."""

import pytest

from signified import Computed, Effect, Signal


@pytest.mark.parametrize("base", [Signal, Computed])
def test_overriding_value_raises(base):
    with pytest.raises(TypeError, match="overrides value"):

        class Clamped(base):
            @property
            def value(self):
                return 0


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


@pytest.mark.parametrize(
    ("base", "name"),
    [(Signal, "notify"), (Signal, "update"), (Computed, "notify"), (Computed, "update"), (Effect, "update")],
)
def test_overriding_methods_the_engine_never_calls_raises(base, name):
    with pytest.raises(TypeError, match=f"overrides {name}"):
        type("Custom", (base,), {name: lambda self: None})


def test_reading_an_uninitialized_signal_raises():
    s = Signal.__new__(Signal)
    with pytest.raises(RuntimeError, match="__init__"):
        s.value
    with pytest.raises(RuntimeError, match="__init__"):
        s.value = 1
    Signal.__init__(s, 2)
    assert s.value == 2


@pytest.mark.parametrize("name", ["value", "update", "notify"])
def test_override_inherited_from_a_mixin_raises(name):
    member = property(lambda self: 99) if name == "value" else (lambda self: None)
    mixin = type("Mixin", (), {name: member})
    with pytest.raises(TypeError, match=f"overrides {name}"):
        type("Custom", (mixin, Signal), {})
