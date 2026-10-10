"""Reactive values cannot be copied; copy the inputs and build new ones."""

import copy
from dataclasses import dataclass

import pytest

from signified import Binding, Computed, Effect, Signal, tracked_fields


@pytest.mark.parametrize("make", [lambda: Signal(1), lambda: Computed(lambda: 1), lambda: Binding(1)])
@pytest.mark.parametrize("duplicate", [copy.copy, copy.deepcopy])
def test_copying_a_reactive_value_raises(make, duplicate):
    value = make()
    with pytest.raises(TypeError, match="cannot be copied"):
        duplicate(value)


def test_copying_an_effect_raises():
    effect = Effect(lambda: None)
    with pytest.raises(TypeError):
        copy.copy(effect)
    effect.dispose()


def test_tracked_field_instances_still_copy():
    @tracked_fields
    @dataclass
    class Material:
        roughness: float = 0.5

    material = Material()
    doubled = Computed(lambda: material.roughness * 2)
    assert doubled.value == 1.0  # the read creates the hidden source
    for duplicate in (copy.copy(material), copy.deepcopy(material)):
        assert duplicate.roughness == 0.5
