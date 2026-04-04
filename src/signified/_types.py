"""Type definitions for reactive programming."""

from __future__ import annotations

import collections.abc
import weakref
from typing import TYPE_CHECKING, Hashable, Iterable, Iterator

if TYPE_CHECKING:
    from ._reactive import Computed, Signal

__all__ = ["NestedValue", "HasValue", "ReactiveValue"]

type ReactiveValue[T] = Computed[T] | Signal[T]
"""A reactive object that would return a value of type T when calling unref(obj)."""

type NestedValue[T] = T | ReactiveValue[NestedValue[T]]
"""Recursive type hint for arbitrarily nested reactive values."""

type HasValue[T] = T | ReactiveValue[T]
"""This object would return a value of type T when calling unref(obj)."""


class _OrderedSet[T](collections.abc.MutableSet[T]):
    """Used to implement a WeakRefSet.

    Yoinked from a Raymond Hettinger stackoverflow post:
        https://stackoverflow.com/a/7829569
    """

    def __init__(self, values: Iterable[T] = ()) -> None:
        self._od = dict.fromkeys(values)

    def __len__(self) -> int:
        return len(self._od)

    def __iter__(self) -> Iterator[T]:
        return iter(self._od)

    def __contains__(self, x: Hashable) -> bool:
        return x in self._od

    def add(self, value: T) -> None:
        self._od[value] = None

    def discard(self, value: T) -> None:
        self._od.pop(value, None)

    def copy(self):
        return type(self)(self._od)


class _ObserverLink[T]:
    """Doubly linked producer -> observer subscription edge."""

    __slots__ = ("observer_ref", "prev", "next")

    def __init__(self, observer_ref: weakref.ReferenceType[T]) -> None:
        self.observer_ref = observer_ref
        self.prev: _ObserverLink[T] | None = None
        self.next: _ObserverLink[T] | None = None


class _ObserverLinks[T]:
    """Store observer subscriptions as explicit producer/consumer links.

    Producers keep a doubly linked list of weak observer refs for cheap notify
    walks, plus a weak-key index for O(1) subscribe/unsubscribe by observer.
    """

    def __init__(self, values: Iterable[T] = ()) -> None:
        self._head: _ObserverLink[T] | None = None
        self._tail: _ObserverLink[T] | None = None
        self._links: weakref.WeakKeyDictionary[T, _ObserverLink[T]] = weakref.WeakKeyDictionary()
        for elem in values:
            self.add(elem)

    def __bool__(self) -> bool:
        return self._head is not None

    def add(self, observer: T) -> None:
        if observer in self._links:
            return

        owner_ref = weakref.ref(self)
        link = _ObserverLink[T](weakref.ref(observer))

        def _cleanup(
            _ref: weakref.ReferenceType[T],
            owner_ref: weakref.ReferenceType[_ObserverLinks[T]] = owner_ref,
            link: _ObserverLink[T] = link,
        ) -> None:
            owner = owner_ref()
            if owner is not None:
                owner._remove_link(link)

        link.observer_ref = weakref.ref(observer, _cleanup)

        tail = self._tail
        if tail is None:
            self._head = link
        else:
            tail.next = link
            link.prev = tail
        self._tail = link
        self._links[observer] = link

    def discard(self, observer: T) -> None:
        link = self._links.pop(observer, None)
        if link is not None:
            self._remove_link(link)

    def iter_alive(self) -> Iterator[T]:
        current = self._head
        while current is not None:
            next_link = current.next
            observer = current.observer_ref()
            if observer is None:
                self._remove_link(current)
            else:
                yield observer
            current = next_link

    def notify(self) -> None:
        current = self._head
        while current is not None:
            next_link = current.next
            observer = current.observer_ref()
            if observer is None:
                self._remove_link(current)
            else:
                observer.update()
            current = next_link

    def _remove_link(self, link: _ObserverLink[T]) -> None:
        prev_link = link.prev
        next_link = link.next

        if prev_link is None:
            self._head = next_link
        else:
            prev_link.next = next_link

        if next_link is None:
            self._tail = prev_link
        else:
            next_link.prev = prev_link

        link.prev = None
        link.next = None
