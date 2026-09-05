"""Replace reactive values inside nested containers with their current values.

For example, ``deep_unref({"x": Signal(1)})`` returns ``{"x": 1}``. Lists,
tuples, dictionaries, sets, frozensets, and deques are rebuilt with their
reactive contents replaced. Supported NumPy arrays are handled too. Other
objects are returned unchanged unless their exact type has a registered handler.

To support an application object, register a function that builds its resolved
replacement. Call the supplied ``resolve`` function on each field you want to
visit; copy other fields directly. For example:

    >>> from dataclasses import dataclass
    >>> from signified import Signal, deep_unref
    >>> @dataclass
    ... class Position:
    ...     x: float | Signal[float]
    ...     y: float | Signal[float]
    >>> @deep_unref.register(Position)
    ... def resolve_position(position, resolve):
    ...     return Position(resolve(position.x), resolve(position.y))
    >>> position = Position(Signal(10.0), Signal(20.0))
    >>> deep_unref({"position": position})
    {'position': Position(x=10.0, y=20.0)}

Position does not deep_ref support by default. Its handler tells deep_unref which fields to visit.
For a custom iterable, the handler can visit its items and preserve metadata:

    >>> class Samples:
    ...     def __init__(self, values, label=""):
    ...         self.values = list(values)
    ...         self.label = label
    ...     def __iter__(self):
    ...         return iter(self.values)
    >>> @deep_unref.register(Samples)
    ... def resolve_samples(samples, resolve):
    ...     values = (resolve(value) for value in samples)
    ...     return Samples(values, label=samples.label)
    >>> samples = Samples([Signal(10), Signal(20)], label="sensor A")
    >>> result = deep_unref(samples)
    >>> list(result), result.label
    ([10, 20], 'sensor A')

Being iterable alone does not opt a custom type into traversal in 0.6.0.
Registering Samples makes that choice explicit and keeps its label intact.

A handler decides which fields to visit and what object to return. Prefer
building a new object without mutating the input. Use the supplied ``resolve``
instead of starting another ``deep_unref`` call, so the same registered handlers
are used throughout the traversal. Each occurrence is resolved independently,
including repeated references. Cyclic inputs eventually raise RecursionError.

Registration applies to exactly the named type; register subclasses separately
when they need the same behavior. See the built-in handlers in this module's
implementation for examples of containers, dictionary keys, and NumPy arrays.

The result is not necessarily JSON-serializable: dates and other unsupported
objects remain as they were. Reads made inside a computation or effect become
normal reactive dependencies.
"""

from __future__ import annotations

import importlib.util
from collections import deque
from typing import Any, Callable, Protocol

from ._reactive import is_reactive

_PLAIN_TYPES = frozenset((int, float, bool, str, bytes, complex, type(None)))


class ResolveContext:
    """Resolve a child within the current traversal.

    Handlers call ``resolve(child)`` for each field they want to visit.
    The supplied context recursively resolves values with the current handlers.
    """

    def __init__(
        self,
        resolvers: dict[type[Any], Callable[..., Any]],
        plain_types: frozenset[type[Any]] | None = None,
    ) -> None:
        self._resolvers = resolvers
        self._plain_types = _PLAIN_TYPES.difference(resolvers) if plain_types is None else plain_types

    def __call__(self, value: Any) -> Any:
        if type(value) in self._plain_types:
            return value
        if is_reactive(value):
            value = value.value
            if type(value) in self._plain_types:
                return value
            return self(value)
        handler = self._resolvers.get(type(value))
        return value if handler is None else handler(value, self)


class _Registration[T](Protocol):
    def __call__[R](self, resolver: Callable[[T, ResolveContext], R]) -> Callable[[T, ResolveContext], R]: ...


class _DeepUnref:
    def __init__(self) -> None:
        self._resolvers: dict[type[Any], Callable[..., Any]] = {}
        self._plain_types = _PLAIN_TYPES
        # With no per-traversal state, a context can serve every call until
        # registration replaces it. In-progress calls keep their old snapshot.
        self._resolve = ResolveContext(self._resolvers, self._plain_types)

    def register[T](self, container_type: type[T]) -> _Registration[T]:
        """Teach deep_unref how to rebuild one application or container type.

        The decorated function receives ``(value, resolve)`` and returns the
        replacement object. Call ``resolve`` on each child that should be
        unwrapped. Leave unrelated metadata alone, and avoid changing the input.

        Only this exact type uses the handler; subclasses need registration
        too. Registering the type again replaces its handler. See the module
        example and the built-in handler implementations for working patterns.
        """

        def decorate[R](resolver: Callable[[T, ResolveContext], R]) -> Callable[[T, ResolveContext], R]:
            # Copy on registration so an in-progress traversal keeps its snapshot.
            self._resolvers = {**self._resolvers, container_type: resolver}
            self._plain_types = _PLAIN_TYPES.difference(self._resolvers)
            self._resolve = ResolveContext(self._resolvers, self._plain_types)
            return resolver

        return decorate

    def __call__(self, value: Any) -> Any:
        """Return value with reactive contents replaced by their current values.

        Supported containers are rebuilt; unknown objects pass through unchanged.
        Repeated references are resolved independently. Cyclic inputs eventually
        raise RecursionError. Dictionary keys or set members that become duplicates
        after unwrapping raise ValueError; unhashable keys or members raise TypeError.

        Reads inside a computation or effect create dependencies.
        """
        return self._resolve(value)


deep_unref = _DeepUnref()
"""Replace reactive values inside nested containers with their current values.

For example, ``deep_unref({"x": Signal(1)})`` returns ``{"x": 1}``. Supported
containers are rebuilt; other objects are returned unchanged. Register a custom
handler with ``@deep_unref.register(MyType)`` to visit fields of an application
object. See the module example and built-in implementations for guidance.
"""


@deep_unref.register(list)
def _list(value: list[Any], resolve: ResolveContext) -> list[Any]:
    return [resolve(item) for item in value]


@deep_unref.register(tuple)
def _tuple(value: tuple[Any, ...], resolve: ResolveContext) -> tuple[Any, ...]:
    return tuple(resolve(item) for item in value)


@deep_unref.register(dict)
def _dict(value: dict[Any, Any], resolve: ResolveContext) -> dict[Any, Any]:
    result = {resolve(key): resolve(item) for key, item in value.items()}
    if len(result) != len(value):
        raise ValueError("Resolved dictionary key collision")
    return result


def _members(value: Any, resolve: ResolveContext) -> set[Any]:
    result = {resolve(item) for item in value}
    if len(result) != len(value):
        raise ValueError("Resolved set member collision")
    return result


@deep_unref.register(set)
def _set(value: set[Any], resolve: ResolveContext) -> set[Any]:
    return _members(value, resolve)


@deep_unref.register(frozenset)
def _frozenset(value: frozenset[Any], resolve: ResolveContext) -> frozenset[Any]:
    return frozenset(_members(value, resolve))


@deep_unref.register(deque)
def _deque(value: deque[Any], resolve: ResolveContext) -> deque[Any]:
    return deque((resolve(item) for item in value), maxlen=value.maxlen)


if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]

    @deep_unref.register(np.ndarray)
    def _ndarray(value: Any, resolve: ResolveContext) -> Any:
        if not value.dtype.hasobject:
            return value
        result = np.empty(value.shape, dtype=value.dtype)
        if value.dtype.names:
            for name in value.dtype.names:
                result[name] = resolve(value[name])
        else:
            for i, item in enumerate(value.flat):
                result.flat[i] = resolve(item)
        return result
