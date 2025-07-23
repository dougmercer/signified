"""Type definitions for reactive programming."""

from __future__ import annotations

import collections.abc
import sys
import weakref
from typing import TYPE_CHECKING, Any, Generic, Iterable, Iterator, TypeVar, Union

if sys.version_info >= (3, 12):
    from typing import TypeAliasType
else:
    from typing_extensions import TypeAliasType

if sys.version_info >= (3, 10):
    from typing import ParamSpec, TypeAlias, TypeGuard
else:
    from typing_extensions import ParamSpec, TypeAlias, TypeGuard

if TYPE_CHECKING:
    from .core import Computed, Signal

# Type variables
T = TypeVar("T")
Y = TypeVar("Y")
R = TypeVar("R")

A = TypeVar("A")
B = TypeVar("B")

P = ParamSpec("P")


class _HasValue(Generic[T]):
    """Class to make pyright happy with type inference."""

    @property
    def value(self) -> T: ...


NestedValue: TypeAlias = Union[T, "_HasValue[NestedValue[T]]"]
"""Recursive type hint for arbitrarily nested reactive values."""


ReactiveValue = TypeAliasType("ReactiveValue", Union["Computed[T]", "Signal[T]"], type_params=(T,))
"""A reactive object that would return a value of type T when calling unref(obj)."""

HasValue = TypeAliasType("HasValue", Union[T, "Computed[T]", "Signal[T]"], type_params=(T,))
"""This object would return a value of type T when calling unref(obj)."""


def has_value(obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check if an object has a value of a specific type."""
    from .utils import unref

    return isinstance(unref(obj), type_)


class OrderedSet(collections.abc.MutableSet):
    """Used to implement a WeakRefSet.

    Yoinked from a Raymond Hettinger stackoverflow post:
        https://stackoverflow.com/a/7829569
    """

    def __init__(self, values: Iterable = ()) -> None:
        self._od = dict.fromkeys(values)

    def __len__(self) -> int:
        return len(self._od)

    def __iter__(self) -> Iterator:
        return iter(self._od)

    def __contains__(self, value: Any) -> bool:
        return value in self._od

    def add(self, value: Any) -> None:
        self._od[value] = None

    def discard(self, value: Any) -> None:
        self._od.pop(value, None)

    def copy(self):
        return type(self)(self._od)


class OrderedWeakrefSet(weakref.WeakSet):
    """Store weakrefs in a set.

    Yoinked from a Raymond Hettinger stackoverflow post:
        https://stackoverflow.com/a/7829569
    """

    def __init__(self, values: Iterable = ()) -> None:
        super().__init__()
        self.data = OrderedSet()
        for elem in values:
            self.add(elem)
