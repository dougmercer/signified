"""Variable Store for tracking and syncing reactive dependency trees"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol
from weakref import WeakKeyDictionary

from .types import _OrderedWeakrefSet as weakset


class weakdict[K, V](WeakKeyDictionary[K, V]):
    def __repr__(self) -> str:
        return str(dict(self))


class Observer(Protocol):
    def update(self) -> None: ...


class Observable(Protocol):
    def __init__(self, *args, **kwargs) -> None:
        self._observers: weakset[Observable]
    def notify(self) -> None: ...
    def update(self) -> None: ...
    

class VariableStore:
    def __init__(self) -> None:
        self.tree: weakdict[Observable, weakset[Observable]] = weakdict()
        self.version: weakdict[Observable, int] = weakdict()

    def __repr__(self) -> str:
        return repr(self.tree)

    def add(self, observable: Observable) -> None:
        if observable in self.tree:
            return

        self.tree[observable] = observable._observers
        self.version[observable] = 0

    def observers_of(self, observable: Observable) -> weakset[Observable]:
        _observers = weakset[Observable]()
        def _get_observers(observable: Observable):
            for observer in observable._observers:
                _observers.add(observer)
                _get_observers(observer)
        _get_observers(observable)
        return _observers

    def mark_dirty(self, observable: Observable) -> None:
        self.version[observable] += 1
        for observer in self.observers_of(observable):
            self.version[observer] += 1

    def is_dirty(self, observable: Observable) -> bool:
        return self.version[observable] != 0

    def propogate(self, variable: Observable) -> None:
        if not self.is_dirty(variable):
            return

        for observer in self.observers_of(variable):
            observer.update()
        self.version[variable] = 0

