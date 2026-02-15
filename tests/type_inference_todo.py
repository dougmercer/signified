"""Known typing gaps for ReactiveMixIn.

To evaluate progress toward desired inference:
1. Change `USE_CURRENT_INFERENCE` to `Literal[False] = False`.
2. Run pyright on this file.

When it's ready, move passing desired assertions into `type_inference.py`.
"""

from typing import Any, Literal, assert_type

from signified import Computed, Signal

# NOTE: Keep annotation/value in sync so pyright can treat this as a constant.
USE_CURRENT_INFERENCE: Literal[True] = True


def test_todo_mixed_bool_int_bitwise():
    # Why this fails:
    # Bitwise ops are typed as Computed[T | Y], so bool/int mixes remain a
    # union rather than being normalized to int.
    if USE_CURRENT_INFERENCE:
        assert_type(Signal(True) & Signal(1), Computed[bool | int])
        assert_type(Signal(True) | Signal(1), Computed[bool | int])
        assert_type(Signal(True) ^ Signal(1), Computed[bool | int])
    else:
        assert_type(Signal(True) & Signal(1), Computed[int])
        assert_type(Signal(True) | Signal(1), Computed[int])
        assert_type(Signal(True) ^ Signal(1), Computed[int])


def test_todo_getattr_data_attributes():
    # Why this fails:
    # __getattr__ is intentionally typed as Computed[Any] for arbitrary
    # attribute names, because static typing can't resolve proxy attributes.
    class Person:
        def __init__(self, name: str, age: int) -> None:
            self.name = name
            self.age = age

    person = Signal(Person("Alice", 30))

    if USE_CURRENT_INFERENCE:
        assert_type(person.name, Computed[Any])
        assert_type(person.age, Computed[Any])
    else:
        assert_type(person.name, Computed[str])
        assert_type(person.age, Computed[int])


def test_todo_getattr_nested_object_attribute():
    # Why this fails:
    # Same proxy limitation as above. Without proxy-aware typing support
    # (or richer intersection/protocol modeling), nested attribute access
    # through __getattr__ remains Computed[Any].
    class Person:
        def __init__(self, name: str) -> None:
            self.name = name

    class Wrapper:
        def __init__(self, person: Person) -> None:
            self.person = person

    wrapped = Signal(Wrapper(Person("Alice")))

    if USE_CURRENT_INFERENCE:
        assert_type(wrapped.person, Computed[Any])
    else:
        assert_type(wrapped.person, Computed[Person])
