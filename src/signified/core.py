"""Core reactive programming functionality."""

from __future__ import annotations


from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Concatenate, Protocol, Self, TypeGuard, cast, overload

from .plugins import pm
from .types import HasValue, ReactiveValue, _OrderedWeakrefSet
from .store import VariableStore
from .rx import ReactiveMixIn

import importlib.util
if importlib.util.find_spec("numpy") is not None:
    import numpy as np
else:
    np = None


__all__ = [
    "Observer",
    "Variable",
    "Signal",
    "Computed",
    "computed",
    "unref",
    "has_value",
    "deep_unref",
    "reactive_method",
    "as_signal",
]


# Global state for tracking variable deps
V_STORE = VariableStore()


def computed[R](func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Wrap a function so calls produce a reactive ``Computed`` result.

    The returned wrapper accepts plain values, reactive values, or nested
    containers that include reactive values. On each recomputation, arguments
    are normalized with :func:`deep_unref`, so ``func`` receives plain Python
    values.

    The created :class:`Computed` subscribes to reactive dependencies found in
    ``args`` and ``kwargs`` at call time. When any dependency updates, the
    function is re-evaluated and subscribers are notified.

    Args:
        func: Function that computes a derived value from its inputs.

    Returns:
        A wrapper that returns a :class:`Computed` when called.

    Example:
        ```py
        >>> @computed
        ... def total(price, quantity):
        ...     return price * quantity
        >>> price = Signal(10)
        >>> quantity = Signal(2)
        >>> subtotal = total(price, quantity)
        >>> subtotal.value
        20
        >>> quantity.value = 3
        >>> subtotal.value
        30

        ```
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        def compute_func() -> R:
            resolved_args = tuple(deep_unref(arg) for arg in args)
            resolved_kwargs = {key: deep_unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func, (*args, *kwargs.values()))

    return wrapper


def _is_truthy(value: Any) -> bool:
    """Convert a value to boolean, handling array-like objects."""
    try:
        return bool(value)
    except ValueError:
        # Handle numpy arrays, pandas Series, etc.
        return bool(value.any())


class Observer(Protocol):
    def update(self) -> None:
        pass


class Variable[T](ABC, ReactiveMixIn[T]):
    """An abstract base class for reactive values.

    A reactive value is an object that can be observed by observer for changes and
    can notify observers when its value changes. This class implements both the observer
    and observable patterns.

    This class implements both the observer and observable pattern.

    Subclasses should implement the `update` method.

    Attributes:
        _observers (list[Observer]): List of observers subscribed to this variable.
        _store (VariableStore): A variable store used to handle dependency updating
    """

    __slots__ = ["_observers", "__name", "__weakref__"]

    def __init__(self, *, _store=V_STORE):
        """Initialize the variable."""
        self._observers = _OrderedWeakrefSet[Observer]()
        self.__name = ""
        self.store = _store
        self.store.add(self)

    @staticmethod
    def _iter_variables(item: Any) -> Generator[Variable[Any]]:
        """Yield `Variable` instances found in arbitrarily nested containers."""
        if isinstance(item, Variable):
            yield item
            return
        if isinstance(item, str):
            return
        if isinstance(item, Iterable):
            for sub_item in item:
                yield from Variable._iter_variables(sub_item)

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
        self._observers.discard(observer)

    def observe(self, items: Any) -> Self:
        """Subscribe the observer (`self`) to all items that are Observable.

        This method handles arbitrarily nested iterables.

        Args:
            items: A single item, an iterable, or a nested structure of items to potentially subscribe to.

        Returns:
            self
        """

        for item in self._iter_variables(items):
            if item is not self:
                item.subscribe(self)
        return self

    def unobserve(self, items: Any) -> Self:
        """Unsubscribe the observer (`self`) from all items that are Observable.

        Args:
            items: A single item or an iterable of items to potentially unsubscribe from.

        Returns:
            self
        """

        for item in self._iter_variables(items):
            if item is not self:
                item.unsubscribe(self)
        return self

    def notify(self) -> None:
        """Notify all observers by calling their update method."""
        self.store.propogate(self)

    def __str__(self) -> str:
        return f"<{self.value}>"

    def __repr__(self) -> str:
        """Represent the object in a way that shows the inner value."""
        return f"{self:n}"

    @abstractmethod
    def update(self) -> None:
        """Update method to be overridden by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError("Update method should be overridden by subclasses")

    def _ipython_display_(self) -> None:
        from .display import _HAS_IPYTHON, IPythonObserver

        if not _HAS_IPYTHON:
            return

        try:
            display = importlib.import_module("IPython.display").display
        except ImportError:
            return

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
            _ident = self.__name if self.__name else f"{type(self).__name__}(id={id(self)})"
            return f"{_ident}: <{self.value}>"
        if format_spec == "d":  # Debug
            name_part = f"name='{self.__name}', " if self.__name else ""
            return f"{type(self).__name__}({name_part}value={self.value!r}, id={id(self)})"
        return super().__format__(format_spec)  # Handles other format specs


def unref[T](value: HasValue[T]) -> T:
    """Resolve a value by unwrapping reactive containers until plain data remains.

    This utility repeatedly unwraps :class:`Variable` objects by following
    their internal ``_value`` references, allowing callers to operate on the
    underlying Python value regardless of nesting depth.

    Args:
        value: Plain value, reactive value, or nested reactive value.

    Returns:
        The fully unwrapped value.

    Example:
        ```py
        >>> nested = Signal(Signal(5))
        >>> unref(nested)
        5

        ```
    """
    current: Any = value
    while isinstance(current, Variable):
        current = current._value
    return current


def has_value[T](obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check whether an object's resolved value is an instance of ``type_``.

    This helper is a typed guard around :func:`unref`. It is useful when code
    accepts either plain values or reactive values and needs a narrowed type
    before continuing.

    Args:
        obj: Value to inspect. May be plain or reactive.
        type_: Expected resolved value type.

    Returns:
        ``True`` if ``unref(obj)`` is an instance of ``type_``; otherwise
        ``False``.

    Example:
        ```py
        >>> candidate = Signal(42)
        >>> has_value(candidate, int)
        True
        >>> has_value(candidate, str)
        False

        ```
    """
    return isinstance(unref(obj), type_)


class Signal[T](Variable[T]):
    """Mutable source-of-truth reactive value.

    ``Signal`` stores a value and notifies subscribers when that value changes.
    It is typically used for application state that should be observed by
    derived :class:`Computed` values.

    The ``value`` property is read/write:
    - reading ``value`` returns the resolved plain value
    - assigning ``value`` updates dependencies and notifies observers when the
      value changed

    Signals can also proxy mutation operations (for example ``__setattr__`` and
    ``__setitem__``) so in-place updates on wrapped objects can still trigger
    reactivity.

    Args:
        value: Initial value to wrap. May be plain or reactive.

    Example:
        ```py
        >>> count = Signal(1)
        >>> doubled = count * 2
        >>> doubled.value
        2
        >>> count.value = 3
        >>> doubled.value
        6

        ```
    """

    __slots__ = ["_value"]

    @overload
    def __init__(self, value: ReactiveValue[T]) -> None: ...

    @overload
    def __init__(self, value: T) -> None: ...

    def __init__(self, value: HasValue[T]) -> None:
        super().__init__()
        self._value: HasValue[T] = value
        self.observe(value)
        pm.hook.created(value=self)

    @property
    def value(self) -> T:
        """Get or set the current value."""
        pm.hook.read(value=self)
        return unref(self._value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        self.unobserve(self._value)
        self._value = new_value
        self.observe(new_value)
        self.store.mark_dirty(self)
        self.store.propogate(self)

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context."""
        before = self.value
        try:
            self.value = value
            yield
        finally:
            self.value = before

    def update(self) -> None:
        """Update the signal and notify subscribers."""
        self.notify()


class Computed[T](Variable[T]):
    """Read-only reactive value derived from a computation.

    ``Computed`` recalculates its value whenever one of its observed
    dependencies updates. In most usage, instances are created implicitly via
    :func:`computed`, operator overloads, or helper APIs such as
    :func:`reactive_method`.

    Unlike :class:`Signal`, ``Computed.value`` is read-only and is updated by
    re-running the stored function.

    Args:
        f: Zero-argument function used to compute the current value.
        dependencies: Dependencies to observe. May be a single item or nested
            container structure.

    Example:
        ```py
        >>> count = Signal(2)
        >>> squared = Computed(lambda: count.value ** 2, dependencies=count)
        >>> squared.value
        4
        >>> count.value = 5
        >>> squared.value
        25

        ```
    """

    __slots__ = ["f", "_value"]

    def __init__(self, f: Callable[..., T], dependencies: Any = None) -> None:
        super().__init__()
        self.f = f
        self.observe(dependencies)
        self._value = unref(self.f())
        self.notify()
        pm.hook.created(value=self)

    def update(self) -> None:
        """Update the value by re-evaluating the function."""
        new_value = self.f()
        if (
            _is_truthy(new_value != self._value)
            or isinstance(self._value, (Generator, Callable))
        ):
            self.store.mark_dirty(self)
            self._value = new_value
            self.store.propogate(self)
            pm.hook.updated(value=self)

    @property
    def value(self) -> T:
        """Get the current value."""
        pm.hook.read(value=self)
        return unref(self._value)


# ---------------------------------------------------------------------------
# Utility functions that depend on the core types above
# ---------------------------------------------------------------------------

_SCALAR_TYPES = {int, float, str, bool, type(None)}


def deep_unref(value: Any) -> Any:
    """Recursively resolve reactive values within nested containers.

    ``deep_unref`` is the structural counterpart to :func:`unref`. It unwraps
    reactive values that appear inside supported containers while preserving the
    container type where practical.

    Supported behavior:
    - scalar primitives are returned unchanged
    - reactive values are unwrapped recursively
    - ``dict``, ``list``, and ``tuple`` contents are recursively unwrapped
    - generic iterables are reconstructed when possible; otherwise returned as-is
    - ``numpy.ndarray`` values with ``dtype=object`` are recursively unwrapped
      element-wise

    Args:
        value: Any value, possibly containing reactive values.

    Returns:
        Value with reactive nodes recursively replaced by plain values.

    Example:
        ```py
        >>> payload = {"a": Signal(1), "b": [Signal(2), 3]}
        >>> deep_unref(payload)
        {'a': 1, 'b': [2, 3]}

        ```
    """
    # Fast path for common scalar types (faster than isinstance check)
    if type(value) in _SCALAR_TYPES:
        return value

    # Base case - if it's a reactive value, unref it
    if isinstance(value, Variable):
        return deep_unref(unref(value))

    # For containers, recursively unref their elements
    if np is not None and isinstance(value, np.ndarray):
        assert np is not None
        return np.array([deep_unref(item) for item in value]).reshape(value.shape) if value.dtype == object else value
    if isinstance(value, dict):
        return {deep_unref(unref(k)): deep_unref(unref(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(deep_unref(item) for item in value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        constructor: Any = type(value)
        try:
            return constructor(deep_unref(item) for item in value)
        except TypeError:
            return value

    return value


type InstanceMethod[**P, T] = Callable[Concatenate[Any, P], T]
type ReactiveMethod[**P, T] = Callable[Concatenate[Any, P], Computed[T]]


def reactive_method[**P, T](*dep_names: str) -> Callable[[InstanceMethod[P, T]], ReactiveMethod[P, T]]:
    """Decorate an instance method so calls return a ``Computed`` value.

    The decorated method keeps its original call signature but now returns a
    reactive value. Dependencies include:
    - instance attributes named in ``dep_names`` (when present), and
    - call-time ``args`` and ``kwargs``.

    This is useful for class APIs where a derived value depends on reactive
    fields owned by ``self``.

    Args:
        *dep_names: Attribute names on ``self`` to observe as dependencies.

    Returns:
        A decorator that transforms an instance method into one that returns
        :class:`Computed`.

    Example:
        ```py
        >>> from signified import Signal, reactive_method
        >>> class Counter:
        ...     def __init__(self):
        ...         self.count = Signal(1)
        ...     @reactive_method("count")
        ...     def doubled(self):
        ...         return self.count.value * 2
        >>> c = Counter()
        >>> result = c.doubled()
        >>> result.value
        2
        >>> c.count.value = 4
        >>> result.value
        8

        ```
    """

    def decorator(func: InstanceMethod[P, T]) -> ReactiveMethod[P, T]:
        @wraps(func)
        def wrapper(self: Any, *args: P.args, **kwargs: P.kwargs) -> Computed[T]:
            object_deps = [getattr(self, name) for name in dep_names if hasattr(self, name)]
            all_deps = (*object_deps, *args, *kwargs.values())
            return Computed(lambda: func(self, *args, **kwargs), all_deps)

        return cast(ReactiveMethod[P, T], wrapper)

    return decorator


def as_signal[T](val: HasValue[T]) -> Signal[T]:
    """Normalize a value to a signal-compatible reactive object.

    If ``val`` is already reactive, it is returned unchanged to avoid wrapping
    an existing reactive node. Otherwise a new :class:`Signal` is created.

    Args:
        val: Plain value or reactive value.

    Returns:
        A reactive value suitable for APIs expecting ``Signal``-like behavior.

    Note:
        Existing reactive values are returned as-is at runtime, including
        ``Computed`` instances.

    Example:
        ```py
        >>> from signified import Signal, as_signal
        >>> as_signal(3).value
        3
        >>> s = Signal(4)
        >>> as_signal(s) is s
        True

        ```
    """
    return cast(Signal[T], val) if isinstance(val, Variable) else Signal(val)

