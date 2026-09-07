"""Explicit recursive resolution without implicit object introspection."""

from __future__ import annotations

import importlib.util
from collections import deque
from typing import Any, Callable, Protocol

from ._functions import unref
from ._reactive import is_reactive


class ResolveContext:
    """Callable child resolver supplied to registered handlers.

    Call ``resolve(child)`` or ``resolve(child, ".field")`` inside a handler.
    The optional path component improves diagnostics. Contexts and their memo
    belong to one deep_unref call; do not retain them for later use.
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
                result = self(unref(value), ".value")
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


class _Registration[T](Protocol):
    def __call__[R](self, resolver: Callable[[T, ResolveContext], R]) -> Callable[[T, ResolveContext], R]: ...


class _DeepUnref:
    def __init__(self) -> None:
        self._resolvers: dict[type[Any], Callable[..., Any]] = {}

    def register[T](self, container_type: type[T]) -> _Registration[T]:
        """Register a handler for one exact type; subclasses do not inherit it.

        A handler receives the object and a callable ResolveContext for its
        children. It defines which children are visited and the result type.
        Registering the same type again replaces its previous handler.
        """

        def decorate[R](resolver: Callable[[T, ResolveContext], R]) -> Callable[[T, ResolveContext], R]:
            self._resolvers[container_type] = resolver
            return resolver

        return decorate

    def __call__(self, value: Any) -> Any:
        """Resolve reactive values recursively through registered exact types.

        Unknown objects pass through untouched and may hide reactive values.
        Aliases in traversed objects are preserved; all encountered cycles
        raise ValueError. Key/member collisions raise ValueError and unhashable
        resolved keys/members raise TypeError, with location diagnostics.

        Reads establish normal reactive dependencies. Compose with untracked()
        to avoid subscribing. This is not serialization or a detached snapshot.
        """
        return ResolveContext(self._resolvers.copy())(value)


deep_unref = _DeepUnref()
"""Recursively resolve registered containers; see the compute contract."""


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


if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]

    @deep_unref.register(np.ndarray)
    def _ndarray(value: Any, resolve: ResolveContext) -> Any:
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
