"""Variable Store for tracking and syncing reactive dependency trees"""

from __future__ import annotations

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
        self.subscriptions: weakdict[Observable, weakset[Observable]] = weakdict()
        self.version: weakdict[Observable, int] = weakdict()

    def __repr__(self) -> str:
        return repr(self.subscriptions)

    def add(self, observable: Observable) -> None:
        self.subscriptions[observable] = observable._observers
        self.mark_clean(observable)

    def observers_of(self, observable: Observable) -> weakset[Observable]:
        _observers = weakset[Observable]()
        def _get_observers(observable: Observable):
            for observer in self.subscriptions.get(observable, []):
                _observers.add(observer)
                _get_observers(observer)
        _get_observers(observable)
        return _observers

    def dependencies_of(self, observer: Observer | Observable) -> weakset[Observable]:
        _dependencies = weakset[Observable]()
        for observable, subscribers in self.subscriptions.items():
            if observer in subscribers:
                _dependencies.add(observable)
        return _dependencies

    def greedy_observers(self, observable: Observable) -> weakset[Observer]:
        """Get observers that don't participate in a dependency chain that can be lazily updated"""
        return weakset(o for o in self.subscriptions[observable] if o not in self.version)

    def mark_dirty(self, *observables: Observable) -> None:
        for observable in observables:
            if observable not in self.version:
                continue
            self.version[observable] += 1

    def mark_clean(self, *observables: Observable) -> None:
        for observable in observables:
            self.version[observable] = 0

    def is_dirty(self, observable: Observable) -> bool:
        return self.version[observable] != 0

    def propagate(self, variable: Observable) -> None:
        if not self.is_dirty(variable):
            return
        self.mark_dirty(*self.observers_of(variable))
