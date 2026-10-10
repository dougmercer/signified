"""Copying reactive values: a copy is a new, independent node."""

import copy
from dataclasses import dataclass

from signified import Binding, Computed, Signal


def test_shallow_copy_of_a_signal_is_independent_and_shares_the_value():
    items = [1, 2]
    s = Signal(items)
    clone = copy.copy(s)
    assert type(clone) is Signal
    assert clone is not s
    assert clone.value is items
    clone.value = [3]
    assert s.value is items


def test_deepcopy_of_a_signal_copies_the_value():
    s = Signal([1, 2])
    clone = copy.deepcopy(s)
    assert clone.value == [1, 2]
    assert clone.value is not s.value
    s.value = [9]
    assert clone.value == [1, 2]


def test_deepcopy_of_a_structure_keeps_shared_signals_shared():
    @dataclass
    class Scene:
        a: Signal[int]
        b: Signal[int]

    shared = Signal(1)
    scene = copy.deepcopy(Scene(shared, shared))
    assert scene.a is scene.b
    assert scene.a is not shared
    assert scene.a.value == 1


def test_copy_keeps_custom_equality_and_name():
    s = Signal([1], equal=lambda a, b: a == b).with_name("items")
    clone = copy.deepcopy(s)
    assert clone._name == "items"
    first = clone.value
    clone.value = [1]
    assert clone.value is first


def test_deepcopy_of_a_computed_recomputes_from_its_function():
    s = Signal(2)
    c = Computed(lambda: s.value * 10)
    assert c.value == 20
    clone = copy.deepcopy(c)
    assert type(clone) is Computed
    assert clone.value == 20
    s.value = 3  # the function reads the original signal, as before the copy
    assert clone.value == 30


def test_deepcopy_of_an_operator_node_reads_the_same_inputs_as_a_lambda_would():
    s = Signal(2)
    doubled = s * 2
    clone = copy.deepcopy(doubled)
    assert clone.value == 4
    s.value = 5
    assert clone.value == 10


def test_deepcopy_of_a_binding_follows_a_copy_of_its_source():
    source = Signal(1)
    binding = Binding(source)
    clone = copy.deepcopy(binding)
    assert clone.value == 1
    assert clone.source is not source
    clone.set(7)
    assert clone.value == 7
    assert binding.value == 1


def test_copied_subclass_keeps_python_attributes():
    class Labeled(Signal):
        __slots__ = ("label",)

    s = Labeled(1)
    s.label = "x"
    clone = copy.copy(s)
    assert type(clone) is Labeled
    assert clone.label == "x"
    assert clone.value == 1
