"""Core reactive programming functionality."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from typing import Any, Callable, Protocol, cast

from .ops import ReactiveMixIn
from .plugins import pm
from .types import HasValue, NestedValue, OrderedWeakrefSet, T, Y, _HasValue
from .utils import unref

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


def _is_truthy(value: Any) -> bool:
    """Convert a value to boolean, handling array-like objects."""
    if hasattr(value, "any") and callable(getattr(value, "any")):
        # Handle numpy arrays, pandas Series, etc.
        return bool(value.any())
    else:
        # Handle regular Python values
        return bool(value)


class Observer(Protocol):
    def update(self) -> None:
        pass


class Variable(ABC, _HasValue[Y], ReactiveMixIn[T]):  # type: ignore[misc]
    """An abstract base class for reactive values.

    A reactive value is an object that can be observed by observer for changes and
    can notify observers when its value changes. This class implements both the observer
    and observable patterns.

    This class implements both the observer and observable pattern.

    Subclasses should implement the `update` method.

    Attributes:
        _observers (list[Observer]): List of observers subscribed to this variable.
    """

    __slots__ = ["_observers", "__name", "__weakref__"]

    def __init__(self):
        """Initialize the variable."""
        self._observers = OrderedWeakrefSet()
        self.__name = ""

    def subscribe(self, observer: Observer) -> None:
        """Subscribe an observer to this variable.

        Args:
            observer: The observer to subscribe.
        """
        self._observers.add(observer)

    def unsubscribe(self, observer: Observer) -> None:
        """Unsubscribe an observer from this variable.

        Args:
            observer: The observer to unsubscribe.
        """
        if observer in self._observers:
            self._observers.discard(observer)

    def observe(self, items: Any) -> Self:
        """Subscribe the observer (`self`) to all items that are Observable.

        This method handles arbitrarily nested iterables.

        Args:
            items: A single item, an iterable, or a nested structure of items to potentially subscribe to.

        Returns:
            self
        """

        def _observe(item: Any) -> None:
            if isinstance(item, Variable) and item is not self:
                item.subscribe(self)
            elif isinstance(item, Iterable) and not isinstance(item, str):
                for sub_item in item:
                    _observe(sub_item)

        _observe(items)
        return self

    def unobserve(self, items: Any) -> Self:
        """Unsubscribe the observer (`self`) from all items that are Observable.

        Args:
            items: A single item or an iterable of items to potentially unsubscribe from.

        Returns:
            self
        """

        def _unobserve(item: Any) -> None:
            if isinstance(item, Variable) and item is not self:
                item.unsubscribe(self)
            elif isinstance(item, Iterable) and not isinstance(item, str):
                for sub_item in item:
                    _unobserve(sub_item)

        _unobserve(items)
        return self

    def notify(self) -> None:
        """Notify all observers by calling their update method."""
        for observer in self._observers:
            observer.update()

    def __repr__(self) -> str:
        """Represent the object in a way that shows the inner value."""
        return f"<{self.value}>"

    @abstractmethod
    def update(self) -> None:
        """Update method to be overridden by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError("Update method should be overridden by subclasses")

    def _ipython_display_(self) -> None:
        from .display import HAS_IPYTHON, IPythonObserver

        if not HAS_IPYTHON:
            return

        from IPython.display import display  # pyright: ignore[reportMissingImports]

        handle = display(self.value, display_id=True)
        assert handle is not None
        IPythonObserver(self, handle)

    def add_name(self, name: str) -> Self:
        self.__name = name
        pm.hook.named(value=self)
        return self

    def __format__(self, format_spec: str) -> str:
        """Format the variable with custom display options.

        Format options:
        :n  - just the name (or type+id if unnamed)
        :d  - full debug info
        empty - just the value in brackets (default)
        """
        if not format_spec:  # Default - just show value in brackets
            return f"<{self.value}>"
        if format_spec == "n":  # Name only
            return self.__name if self.__name else f"{type(self).__name__}(id={id(self)})"
        if format_spec == "d":  # Debug
            name_part = f"name='{self.__name}', " if self.__name else ""
            return f"{type(self).__name__}({name_part}value={self.value!r}, id={id(self)})"
        return super().__format__(format_spec)  # Handles other format specs


class Signal(Variable[NestedValue[T], T]):
    """A container that holds a reactive value."""

    __slots__ = ["_value"]

    def __init__(self, value: NestedValue[T]) -> None:
        super().__init__()
        self._value: T = cast(T, value)
        self.observe(value)
        pm.hook.created(value=self)

    @property
    def value(self) -> T:
        """Get or set the current value."""
        pm.hook.read(value=self)
        return unref(self._value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        old_value = self._value
        change = new_value != old_value
        change = _is_truthy(change) if not callable(old_value) else True
        if change:
            self._value = cast(T, new_value)
            pm.hook.updated(value=self)
            self.unobserve(old_value)
            self.observe(new_value)
            self.notify()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context."""
        before = self.value
        try:
            before = self.value
            self.value = value
            yield
        finally:
            self.value = before

    def update(self) -> None:
        """Update the signal and notify subscribers."""
        self.notify()


class Computed(Variable[T, T]):
    """A reactive value defined by a function."""

    __slots__ = ["f", "_value"]

    def __init__(self, f: Callable[[], T], dependencies: Any = None) -> None:
        super().__init__()
        self.f = f
        self.observe(dependencies)
        self._value = unref(self.f())
        self.notify()
        pm.hook.created(value=self)

    def update(self) -> None:
        """Update the value by re-evaluating the function."""
        new_value = self.f()
        change = new_value != self._value
        change = _is_truthy(change) if not callable(self._value) else True
        if change:
            self._value: T = new_value
            pm.hook.updated(value=self)
            self.notify()

    @property
    def value(self) -> T:
        """Get the current value."""
        pm.hook.read(value=self)
        return unref(self._value)
