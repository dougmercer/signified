"""Explicit recursive resolution helpers.

Use this module when every reactive value reachable through an argument should
be read. Normal :func:`signified.computed` and :func:`signified.effect` only
unwrap their direct reactive arguments.
"""

from __future__ import annotations

import importlib.util
from collections import deque
from functools import wraps
from typing import Any, Callable, cast

from ._functions import computed as _computed
from ._functions import effect as _effect
from ._functions import unref as _shallow_unref
from ._reactive import Computed, Effect, _is_reactive_value

__all__ = ["unref", "computed", "effect", "register"]

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None

_SCALAR_TYPES = {int, float, str, bool, bytes, complex, type(None)}
type _Resolve = Callable[[Any], Any]
type _Resolver[T] = Callable[[T, _Resolve], Any]
_RESOLVERS: dict[type[Any], _Resolver[Any]] = {}


def register[T](container_type: type[T]) -> Callable[[_Resolver[T]], _Resolver[T]]:
    """Register recursive resolution for one concrete container type.

    The decorated resolver receives the container and a callback that applies
    deep resolution to a child. Registrations match exact types so an unknown
    iterable or subclass is never consumed implicitly.

    Args:
        container_type: Exact type handled by the decorated resolver.

    Returns:
        A decorator that installs and returns the resolver.

    Example:
        ```py
        >>> class Box:
        ...     def __init__(self, value):
        ...         self.value = value

        >>> @register(Box)
        ... def resolve_box(box, resolve):
        ...     return Box(resolve(box.value))

        ```
    """

    def decorator(resolver: _Resolver[T]) -> _Resolver[T]:
        _RESOLVERS[container_type] = cast(_Resolver[Any], resolver)
        return resolver

    return decorator


@register(list)
def _resolve_list(value: list[Any], resolve: _Resolve) -> list[Any]:
    return [resolve(item) for item in value]


@register(tuple)
def _resolve_tuple(value: tuple[Any, ...], resolve: _Resolve) -> tuple[Any, ...]:
    return tuple(resolve(item) for item in value)


@register(dict)
def _resolve_dict(value: dict[Any, Any], resolve: _Resolve) -> dict[Any, Any]:
    return {resolve(key): resolve(item) for key, item in value.items()}


@register(set)
def _resolve_set(value: set[Any], resolve: _Resolve) -> set[Any]:
    return {resolve(item) for item in value}


@register(frozenset)
def _resolve_frozenset(value: frozenset[Any], resolve: _Resolve) -> frozenset[Any]:
    return frozenset(resolve(item) for item in value)


@register(deque)
def _resolve_deque(value: deque[Any], resolve: _Resolve) -> deque[Any]:
    return deque((resolve(item) for item in value), maxlen=value.maxlen)


if np is not None:

    @register(np.ndarray)
    def _resolve_ndarray(value: Any, resolve: _Resolve) -> Any:
        assert np is not None
        if value.dtype != object:
            return value
        return np.array([resolve(item) for item in value.flat]).reshape(value.shape)


def unref(value: Any) -> Any:
    """Recursively unwrap reactive values and supported containers.

    Registered containers are rebuilt with every reachable reactive value
    resolved. Built-in registrations cover `dict`, `list`, `tuple`, `set`,
    `frozenset`, `collections.deque`, and object-dtype NumPy arrays. Unknown
    objects remain opaque unless registered with [register][signified.deep.register].
    Reading this function during a computation tracks every reactive value
    traversed.

    Raises:
        ValueError: If recursive resolution encounters a cycle.
    """
    active: set[int] = set()

    def resolve(current: Any) -> Any:
        current_type = type(current)
        if current_type in _SCALAR_TYPES:
            return current

        is_reactive = _is_reactive_value(current)
        resolver = _RESOLVERS.get(current_type)
        if not is_reactive and resolver is None:
            return current

        identity = id(current)
        if identity in active:
            raise ValueError(f"Cycle detected while resolving {current_type.__name__}")
        active.add(identity)
        try:
            if is_reactive:
                return resolve(_shallow_unref(current))
            assert resolver is not None
            return resolver(current, resolve)
        finally:
            active.remove(identity)

    return resolve(value)


def computed[R](func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Make a computed function that recursively resolves every argument."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        @_computed
        def call() -> R:
            return func(
                *(unref(arg) for arg in args),
                **{key: unref(value) for key, value in kwargs.items()},
            )

        return call()

    return wrapper


def effect(func: Callable[..., None]) -> Callable[..., Effect]:
    """Make an effect function that recursively resolves every argument."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Effect:
        @_effect
        def call() -> None:
            func(
                *(unref(arg) for arg in args),
                **{key: unref(value) for key, value in kwargs.items()},
            )

        return call()

    return wrapper
