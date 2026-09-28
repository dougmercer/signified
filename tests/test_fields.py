"""Tests for tracked_fields."""

import copy
import dataclasses
import pickle
from dataclasses import dataclass, field

import pytest

from signified import Computed, Effect, HasValue, Signal, tracked_fields, unref


@tracked_fields
@dataclass(slots=True)
class SlotMaterial:
    roughness: HasValue[float] = 0.5
    tags: list[str] = field(default_factory=list)


@tracked_fields
@dataclass
class DictMaterial:
    roughness: HasValue[float] = 0.5
    tags: list[str] = field(default_factory=list)


materials = pytest.mark.parametrize("cls", [SlotMaterial, DictMaterial])


def _counting(read):
    calls = []
    return Computed(lambda: calls.append(1) or read()), calls


@materials
def test_reassignment_and_inner_signal_are_tracked(cls):
    m = cls()
    packed = Computed(lambda: unref(m.roughness) * 2)
    assert packed.value == 1.0
    m.roughness = 0.25
    assert packed.value == 0.5
    s = Signal(0.1)
    m.roughness = s
    assert packed.value == 0.2
    s.value = 0.3
    assert packed.value == 0.6


@materials
def test_reads_return_exactly_what_was_stored(cls):
    s = Signal(0.1)
    m = cls(roughness=s)
    assert m.roughness is s
    assert Computed(lambda: m.roughness).value is s


@materials
def test_assigning_an_equal_value_or_same_object_does_not_invalidate(cls):
    s = Signal(0.1)
    m = cls()
    derived, calls = _counting(lambda: unref(m.roughness))
    assert derived.value == 0.5
    m.roughness = 0.5
    assert derived.value == 0.5
    m.roughness = s
    m.roughness = s
    assert derived.value == 0.1
    assert len(calls) == 2


@materials
def test_assigning_a_signal_replaces_the_source_without_writing_into_it(cls):
    first, second = Signal(1.0), Signal(2.0)
    m = cls(roughness=first)
    assert Computed(lambda: unref(m.roughness)).value == 1.0
    m.roughness = second
    assert first.value == 1.0


@materials
def test_effect_tracks_reassignment(cls):
    m = cls()
    seen = []
    watcher = Effect(lambda: seen.append(unref(m.roughness)))
    m.roughness = 0.8
    assert seen == [0.5, 0.8]
    watcher.dispose()


@materials
@pytest.mark.parametrize("duplicate", [copy.copy, copy.deepcopy, lambda m: pickle.loads(pickle.dumps(m))])
def test_copies_are_independent_after_tracked_reads(cls, duplicate):
    m = cls()
    original = Computed(lambda: unref(m.roughness))
    assert original.value == 0.5

    clone = duplicate(m)
    cloned = Computed(lambda: unref(clone.roughness))
    assert cloned.value == 0.5
    clone.roughness = 0.9
    assert (m.roughness, original.value, cloned.value) == (0.5, 0.5, 0.9)
    m.roughness = 0.7
    assert (clone.roughness, original.value, cloned.value) == (0.9, 0.7, 0.9)


@materials
def test_dataclass_machinery_still_works(cls):
    m = cls(roughness=0.3)
    assert Computed(lambda: m.roughness).value == 0.3
    replaced = dataclasses.replace(m, roughness=0.1)
    assert (replaced.roughness, m.roughness) == (0.1, 0.3)
    assert cls() == cls()
    assert repr(cls()) == f"{cls.__name__}(roughness=0.5, tags=[])"
    assert [f.name for f in dataclasses.fields(cls)] == ["roughness", "tags"]
    assert cls().tags is not cls().tags


@materials
def test_in_place_mutation_is_not_observed(cls):
    m = cls()
    size = Computed(lambda: len(m.tags))
    assert size.value == 0
    m.tags.append("glass")
    assert size.value == 0


@materials
def test_fields_cannot_be_deleted(cls):
    with pytest.raises(AttributeError, match="cannot be deleted"):
        del cls().roughness


def test_names_track_only_listed_fields():
    @tracked_fields("roughness")
    @dataclass(slots=True)
    class Material:
        roughness: float = 0.5
        metallic: float = 0.0

    m = Material()
    derived, calls = _counting(lambda: m.roughness + m.metallic)
    assert derived.value == 0.5
    m.metallic = 1.0
    assert derived.value == 0.5
    m.roughness = 0.25
    assert derived.value == 1.25
    assert len(calls) == 2


def test_plain_class_with_slots_and_names():
    @tracked_fields("_matrix_source")
    class Obj:
        __slots__ = ("_matrix_source",)

        def __init__(self, source):
            self._matrix_source = source

    obj = Obj(Signal(1))
    derived = Computed(lambda: unref(obj._matrix_source) * 10)
    assert derived.value == 10
    obj._matrix_source = Signal(2)
    assert derived.value == 20


def test_plain_class_attribute_default_is_used_until_assigned():
    @tracked_fields("alpha", "label")
    class Obj:
        alpha = 1.0
        label = None

    obj = Obj()
    derived = Computed(lambda: (obj.alpha, obj.label))
    assert derived.value == (1.0, None)
    obj.alpha = 0.5
    assert derived.value == (0.5, None)
    assert Obj().alpha == 1.0


def test_subclass_keeps_inherited_tracking_and_can_track_its_own_fields():
    @tracked_fields
    @dataclass(slots=True)
    class Glass(SlotMaterial):
        ior: float = 1.5

    g = Glass()
    derived = Computed(lambda: unref(g.roughness) + g.ior)
    assert derived.value == 2.0
    g.roughness = 1.0
    assert derived.value == 2.5
    g.ior = 2.0
    assert derived.value == 3.0


def test_rejects_frozen_dataclass_plain_class_without_names_and_existing_descriptors():
    @dataclass(frozen=True)
    class Frozen:
        x: int = 0

    class Plain:
        pass

    class WithProperty:
        @property
        def x(self):
            return 1

    with pytest.raises(TypeError, match="frozen"):
        tracked_fields(Frozen)
    with pytest.raises(TypeError, match="names"):
        tracked_fields(Plain)
    with pytest.raises(TypeError, match="descriptor"):
        tracked_fields("x")(WithProperty)
    with pytest.raises(TypeError, match="class or attribute names"):
        tracked_fields(1)  # pyright: ignore[reportArgumentType, reportCallIssue]
