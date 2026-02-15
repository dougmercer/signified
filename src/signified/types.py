"""Type definitions for reactive programming."""

from __future__ import annotations

import collections.abc
import weakref
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:
    from .core import Computed, Signal

__all__ = ["NestedValue", "HasValue", "ReactiveValue", "OrderedWeakrefSet"]

type ReactiveValue[T] = Computed[T] | Signal[T]
"""A reactive object that would return a value of type T when calling unref(obj)."""

type NestedValue[T] = T | ReactiveValue[NestedValue[T]]
"""Recursive type hint for arbitrarily nested reactive values."""

type HasValue[T] = T | ReactiveValue[T]
"""This object would return a value of type T when calling unref(obj)."""


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

    def __contains__(self, x: Any) -> bool:
        return x in self._od

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
