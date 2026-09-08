"""Replace reactive values inside nested containers with their current values.

For example, ``deep_unref({"x": Signal(1)})`` returns ``{"x": 1}``. Lists,
tuples, dictionaries, sets, frozensets, and deques are rebuilt with their
reactive contents replaced. Supported NumPy arrays are handled too. Other
objects are returned unchanged unless their exact type has a registered handler.
Unregistered iterables still use legacy reconstruction with a DeprecationWarning;
that fallback will be removed in 0.6.0. Register a handler to keep traversing them.

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
    ...     return Position(resolve(position.x, ".x"), resolve(position.y, ".y"))
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
    ...     values = (resolve(value, f"[{i}]") for i, value in enumerate(samples))
    ...     return Samples(values, label=samples.label)
    >>> samples = Samples([Signal(10), Signal(20)], label="sensor A")
    >>> result = deep_unref(samples)
    >>> list(result), result.label
    ([10, 20], 'sensor A')

Being iterable alone does not opt a custom type into traversal in 0.6.0.
Registering Samples makes that choice explicit and keeps its label intact.

A handler decides which fields to visit and what object to return. Prefer
building a new object without mutating the input. Use the supplied ``resolve``
instead of starting another ``deep_unref`` call, so shared references and cycle
checks work across the whole traversal. The optional field label improves error
messages. Handlers run once per encountered object, even if it appears repeatedly.

Registration applies to exactly the named type; register subclasses separately
when they need the same behavior. See the built-in handlers in this module's
implementation for examples of containers, dictionary keys, and NumPy arrays.

The result is not necessarily JSON-serializable: dates and other unsupported
objects remain as they were. Reads made inside a computation or effect become
normal reactive dependencies.
"""

from __future__ import annotations

import importlib.util
import os
from collections import deque
from collections.abc import Iterable
from typing import Any, Callable, Protocol
from warnings import warn

from ._reactive import _track_read, is_reactive


class ResolveContext:
    """Resolve a child value while handling a custom object.

    Call ``resolve(child)`` to replace reactive values inside a field. You can
    add a label, such as ``resolve(child, ".items")``, to show where an error
    happened. Use the instance passed to your handler; do not create or retain
    one yourself. It tracks shared objects and cycles for the current call.
    """

    def __init__(self, resolvers: dict[type[Any], Callable[..., Any]]) -> None:
        self._resolvers = resolvers
        self._memo: dict[int, tuple[Any, Any]] = {}
        self._active: dict[int, str] = {}
        self._path = "$"

    def __call__(self, value: Any, path_component: str = "") -> Any:
        previous = self._path
        self._path += path_component
        try:
            return self._resolve(value)
        finally:
            self._path = previous

    def _resolve(self, value: Any) -> Any:
        reactive = is_reactive(value)
        resolver = self._resolvers.get(type(value))
        if not reactive and resolver is None:
            if isinstance(value, Iterable) and not isinstance(value, str):
                resolver = _legacy_iterable
            else:
                return value
        identity = id(value)
        if identity in self._active:
            raise ValueError(
                f"Cycle detected while resolving {type(value).__name__} at {self._path}; "
                f"already visiting {self._active[identity]}"
            )
        if identity in self._memo:
            return self._memo[identity][1]
        self._active[identity] = self._path
        try:
            if reactive:
                # Read one stored boundary: public unref still follows the whole
                # chain before 0.6, which would bypass this call's cycle checks.
                if value._IS_COMPUTED:
                    value._impl.ensure_uptodate()
                _track_read(value)
                result = self(value._value, ".value")
            else:
                assert resolver is not None
                result = resolver(value, self)
            # Keep sources alive too: handler-generated temporary objects may
            # otherwise die and have their ids reused during this traversal.
            self._memo[identity] = (value, result)
            return result
        except Exception as error:
            error.add_note(f"While resolving {type(value).__name__} at {self._path}")
            raise
        finally:
            del self._active[identity]


class _ChildResolutionError(Exception):
    """Carry a child TypeError past legacy constructor error handling."""

    def __init__(self, error: TypeError) -> None:
        self.error = error


def _legacy_iterable(value: Any, resolve: ResolveContext) -> Any:
    """Keep pre-0.6 iterable reconstruction while callers migrate to handlers."""
    warn(
        f"Automatic traversal of unregistered iterable type {type(value).__name__} "
        "is deprecated and will be removed in 0.6.0. Register a handler with "
        "deep_unref.register(Type) to keep resolving its contents.",
        DeprecationWarning,
        stacklevel=2,
        skip_file_prefixes=(os.path.dirname(__file__),),
    )
    if np is not None and isinstance(value, np.ndarray):
        return _ndarray(value, resolve)

    def children():
        for i, child in enumerate(value):
            try:
                yield resolve(child, f"[{i}]")
            except TypeError as error:
                raise _ChildResolutionError(error) from error

    try:
        return type(value)(children())
    except _ChildResolutionError as error:
        raise error.error
    except TypeError:
        # Some iterable types do not accept an iterable constructor argument.
        return value


class _Registration[T](Protocol):
    def __call__[R](self, resolver: Callable[[T, ResolveContext], R]) -> Callable[[T, ResolveContext], R]: ...


class _DeepUnref:
    def __init__(self) -> None:
        self._resolvers: dict[type[Any], Callable[..., Any]] = {}

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
            self._resolvers[container_type] = resolver
            return resolver

        return decorate

    def __call__(self, value: Any) -> Any:
        """Return value with reactive contents replaced by their current values.

        Supported containers are rebuilt. Unregistered iterables still use
        legacy reconstruction with a DeprecationWarning; that fallback will be
        removed in 0.6.0. Register a handler to keep resolving a custom type.
        Other unknown objects pass through unchanged.
        Shared objects stay shared in the result. Cycles raise ValueError, as do
        dictionary keys or set members that become duplicates after unwrapping.
        Unhashable keys or members raise TypeError. Errors include their location.

        Reads inside a computation or effect create dependencies.
        """
        return ResolveContext(self._resolvers.copy())(value)


deep_unref = _DeepUnref()
"""Replace reactive values inside nested containers with their current values.

For example, ``deep_unref({"x": Signal(1)})`` returns ``{"x": 1}``. Supported
containers are rebuilt; other objects are returned unchanged. Register a custom
handler with ``@deep_unref.register(MyType)`` to visit fields of an application
object. See the module example and built-in implementations for guidance.
"""


@deep_unref.register(list)
def _list(value: list[Any], resolve: ResolveContext) -> list[Any]:
    return [resolve(item, f"[{i}]") for i, item in enumerate(value)]


@deep_unref.register(tuple)
def _tuple(value: tuple[Any, ...], resolve: ResolveContext) -> tuple[Any, ...]:
    return tuple(resolve(item, f"[{i}]") for i, item in enumerate(value))


def _check_member(value: Any, path: str, seen: dict[Any, str]) -> None:
    try:
        hash(value)
    except TypeError as error:
        raise TypeError(f"Unhashable resolved key/member at {path}") from error
    if value in seen:
        raise ValueError(f"Resolved key/member collision at {path} and {seen[value]}")
    seen[value] = path


@deep_unref.register(dict)
def _dict(value: dict[Any, Any], resolve: ResolveContext) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    seen: dict[Any, str] = {}
    for i, (key, item) in enumerate(value.items()):
        key_path = f".keys[{i}]"
        resolved_key = resolve(key, key_path)
        _check_member(resolved_key, resolve._path + key_path, seen)
        result[resolved_key] = resolve(item, f".values[{i}]")
    return result


def _members(value: Any, resolve: ResolveContext) -> list[Any]:
    seen: dict[Any, str] = {}
    result = []
    for i, item in enumerate(value):
        path = f"[{i}]"
        resolved = resolve(item, path)
        _check_member(resolved, resolve._path + path, seen)
        result.append(resolved)
    return result


@deep_unref.register(set)
def _set(value: set[Any], resolve: ResolveContext) -> set[Any]:
    return set(_members(value, resolve))


@deep_unref.register(frozenset)
def _frozenset(value: frozenset[Any], resolve: ResolveContext) -> frozenset[Any]:
    return frozenset(_members(value, resolve))


@deep_unref.register(deque)
def _deque(value: deque[Any], resolve: ResolveContext) -> deque[Any]:
    return deque((resolve(item, f"[{i}]") for i, item in enumerate(value)), maxlen=value.maxlen)


np = None
if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]

    @deep_unref.register(np.ndarray)
    def _ndarray(value: Any, resolve: ResolveContext) -> Any:
        assert np is not None
        if not value.dtype.hasobject:
            return value
        result = np.empty(value.shape, dtype=value.dtype)
        if value.dtype.names:
            for name in value.dtype.names:
                result[name] = resolve(value[name], f".{name}")
        else:
            for i, item in enumerate(value.flat):
                result.flat[i] = resolve(item, f".flat[{i}]")
        return result
