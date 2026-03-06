"""Function helpers for :mod:`signified` reactive objects."""

from __future__ import annotations

import importlib.util
import warnings
from collections.abc import Iterable
from functools import wraps
from typing import Any, Callable, Concatenate, TypeGuard, cast

from ._reactive import Computed, Signal, Variable, _track_read
from ._types import HasValue, ReactiveValue

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None  # User does not have numpy installed


def computed[R](func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Wrap a function so calls produce a reactive [Computed][signified.Computed] result.

    The returned wrapper accepts plain values, reactive values, or nested
    containers. On each recomputation, arguments are resolved with
    [deep_unref][signified.deep_unref], so `func` always receives plain Python values.

    Any reactive value read during evaluation becomes a dependency; the
    [Computed][signified.Computed] updates automatically when any dependency changes.

    Args:
        func: Function that computes a derived value from its inputs.

    Returns:
        A wrapper that returns a [Computed][signified.Computed] when called.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        def compute_func() -> R:
            resolved_args = tuple(deep_unref(arg) for arg in args)
            resolved_kwargs = {key: deep_unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func)

    return wrapper


def unref[T](value: HasValue[T]) -> T:
    """Unwrap a reactive value to its plain Python value.

    Repeatedly follows the `.value` chain until a non-reactive value is
    reached. When called inside a [Computed][signified.Computed] or [Effect][signified.Effect] evaluation,
    each unwrapped reactive registers as a dependency — equivalent to
    reading `.value` directly.

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
        if isinstance(current, Computed):
            current._impl.ensure_uptodate()
        _track_read(current)
        current = current._value
    return current


def has_value[T](obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check whether an object's resolved value is an instance of `type_`.

    A typed guard around [unref][signified.unref]. Useful when a parameter accepts either a
    plain value or a reactive wrapper and you need to narrow the type.

    Args:
        obj: Value to inspect. May be plain or reactive.
        type_: Expected resolved value type.

    Returns:
        `True` if `unref(obj)` is an instance of `type_`; otherwise `False`.

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


# ---------------------------------------------------------------------------
# Utility functions that depend on the reactive types above
# ---------------------------------------------------------------------------

_SCALAR_TYPES = {int, float, str, bool, type(None)}


def deep_unref(value: Any) -> Any:
    """Recursively resolve reactive values within nested containers.

    Like [unref][signified.unref], but also descends into `dict`, `list`, `tuple`, and other
    iterables, replacing any reactive values found within them.

    Supported containers:

    - scalars (`int`, `float`, `str`, `bool`, `None`) are returned unchanged
    - reactive values are unwrapped recursively
    - `dict`, `list`, and `tuple` contents are recursively unwrapped
    - generic iterables are reconstructed when possible; otherwise returned as-is
    - `numpy.ndarray` with `dtype=object` is unwrapped element-wise

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

    # Base case - if it's a reactive value, resolve through `.value` so reads
    # are tracked while inside computed evaluations.
    if isinstance(value, Variable):
        return deep_unref(value.value)

    # For containers, recursively unref their elements
    if np is not None and isinstance(value, np.ndarray):
        assert np is not None
        return np.array([deep_unref(item) for item in value]).reshape(value.shape) if value.dtype == object else value
    if isinstance(value, dict):
        return {deep_unref(k): deep_unref(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(deep_unref(item) for item in value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        constructor: Any = type(value)
        try:
            return constructor(deep_unref(item) for item in value)
        except TypeError:
            return value

    return value


def reactive_method[**P, T](
    *dep_names: str,
) -> Callable[[Callable[Concatenate[Any, P], T]], Callable[Concatenate[Any, P], Computed[T]]]:
    """Deprecated helper for method-style computed values.

    This decorator now delegates to :func:`computed`. It is retained only for
    backwards compatibility and will be removed in a future release.

    Args:
        *dep_names: Deprecated compatibility argument. Ignored.

    Returns:
        A decorator that transforms an instance method into one that returns
        :class:`Computed`.
    """

    warnings.warn(
        "`reactive_method(...)` is deprecated and will be removed in a future "
        "release; use `@computed` instead. Any dependency-name arguments are "
        "ignored.",
        DeprecationWarning,
        stacklevel=2,
    )

    def decorator(func: Callable[Concatenate[Any, P], T]) -> Callable[Concatenate[Any, P], Computed[T]]:
        return cast(Callable[Concatenate[Any, P], Computed[T]], computed(func))

    return decorator


def as_rx[T](val: HasValue[T]) -> ReactiveValue[T]:
    """Normalize a value to a reactive object.

    If `val` is already reactive, it is returned unchanged. Otherwise a new
    [Signal][signified.Signal] is created wrapping the value.

    Args:
        val: Plain value or reactive value.

    Returns:
        A reactive value.
    """
    return cast(ReactiveValue[T], val) if isinstance(val, Variable) else Signal(val)


def as_signal[T](val: HasValue[T]) -> Signal[T]:
    """Deprecated alias for :func:`as_rx`.

    Existing reactive values are returned as-is at runtime, including
    ``Computed`` instances.
    """
    warnings.warn(
        "`as_signal(...)` is deprecated and will be removed in a future release; use `as_rx(...)` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return cast(Signal[T], as_rx(val))
