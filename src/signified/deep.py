"""Explicit recursive resolution helpers.

Use this module when every reactive value reachable through an argument should
be read. Normal :func:`signified.computed` and :func:`signified.effect` only
unwrap their direct reactive arguments.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable
from functools import wraps
from typing import Any, Callable

from ._functions import computed as _computed
from ._functions import effect as _effect
from ._functions import unref as _shallow_unref
from ._reactive import Computed, Effect, _is_reactive_value

__all__ = ["unref", "computed", "effect"]

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None

_SCALAR_TYPES = {int, float, str, bool, bytes, complex, type(None)}


def unref(value: Any) -> Any:
    """Recursively unwrap reactive values and supported containers.

    Dictionaries, lists, tuples, generic iterables, and object-dtype NumPy
    arrays are rebuilt with every reachable reactive value resolved. Reading
    this function during a computation tracks every reactive value traversed.
    """
    value_type = type(value)
    if value_type in _SCALAR_TYPES:
        return value

    if _is_reactive_value(value):
        return unref(_shallow_unref(value))

    if np is not None and isinstance(value, np.ndarray):
        assert np is not None
        if value.dtype != object:
            return value
        return np.array([unref(item) for item in value.flat]).reshape(value.shape)
    if value_type is list:
        return [unref(item) for item in value]
    if value_type is tuple:
        return tuple(unref(item) for item in value)
    if value_type is dict:
        return {unref(key): unref(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, str):
        try:
            return value_type(unref(item) for item in value)
        except TypeError:
            return value

    return value


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
