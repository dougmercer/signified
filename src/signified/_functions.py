"""Function helpers for :mod:`signified` reactive objects."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable
from functools import wraps
from typing import Any, Callable, TypeGuard, cast

from ._reactive import Computed, Effect, Signal, _is_reactive_value, _track_read
from ._types import HasValue, ReactiveValue

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None  # User does not have numpy installed

_PLAIN_ARG_TYPES = {int, float, str, bool, bytes, complex, type(None)}


def _identity[T](value: T) -> T:
    return value


def _get_unref_op(value: Any) -> Callable[[Any], Any]:
    if _is_reactive_value(value):
        return unref
    if type(value) in _PLAIN_ARG_TYPES:
        return _identity
    return deep_unref


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
        # Fast Paths:
        if not kwargs:
            if not args:
                return Computed(func)
            if len(args) == 1:
                arg = args[0]
                resolve_arg = _get_unref_op(arg)
                return Computed(lambda: func(resolve_arg(arg)))
            if len(args) == 2:
                left, right = args
                resolve_left = _get_unref_op(left)
                resolve_right = _get_unref_op(right)
                return Computed(lambda: func(resolve_left(left), resolve_right(right)))

        # General Case:
        arg_resolvers = tuple(_get_unref_op(arg) for arg in args)
        kw_resolvers = {key: _get_unref_op(value) for key, value in kwargs.items()}

        def compute_func() -> R:
            resolved_args = tuple(resolver(arg) for resolver, arg in zip(arg_resolvers, args, strict=False))
            resolved_kwargs = {key: kw_resolvers[key](value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func)

    return wrapper


def effect(func: Callable[..., None]) -> Callable[..., Effect]:
    """Wrap a function so calls produce a reactive [Effect][signified.Effect].

    The returned wrapper accepts plain values, reactive values, or nested
    containers. On each re-run, arguments are resolved with
    [deep_unref][signified.deep_unref], so `func` always receives plain Python values.

    The effect runs immediately when called and re-runs whenever any reactive
    dependency changes. It is active as long as the caller holds a reference to
    the returned [Effect][signified.Effect].

    Args:
        func: Function run for its side effects.

    Returns:
        A wrapper that returns an [Effect][signified.Effect] when called.

    Example:
        ```py
        >>> seen = []
        >>> s = Signal(1)

        >>> @effect
        ... def log(x):
        ...     seen.append(x)

        >>> e = log(s)
        >>> seen
        [1]
        >>> s.value = 2
        >>> seen
        [1, 2]
        >>> e.dispose()
        >>> s.value = 3
        >>> seen
        [1, 2]

        ```
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Effect:
        # Fast Paths:
        if not kwargs:
            if not args:
                return Effect(func)
            if len(args) == 1:
                arg = args[0]
                resolve_arg = _get_unref_op(arg)
                return Effect(lambda: func(resolve_arg(arg)))
            if len(args) == 2:
                left, right = args
                resolve_left = _get_unref_op(left)
                resolve_right = _get_unref_op(right)
                return Effect(lambda: func(resolve_left(left), resolve_right(right)))

        # General Case:
        arg_resolvers = tuple(_get_unref_op(arg) for arg in args)
        kw_resolvers = {key: _get_unref_op(value) for key, value in kwargs.items()}

        def effect_fn() -> None:
            resolved_args = tuple(resolver(arg) for resolver, arg in zip(arg_resolvers, args, strict=False))
            resolved_kwargs = {key: kw_resolvers[key](value) for key, value in kwargs.items()}
            func(*resolved_args, **resolved_kwargs)

        return Effect(effect_fn)

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
    while _is_reactive_value(current):
        if current._IS_COMPUTED:
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
    value_type = type(value)

    # Fast path for common scalar types (faster than isinstance check)
    if value_type in _SCALAR_TYPES:
        return value

    # Unwrap reactive values.
    value = unref(value)
    value_type = type(value)
    if value_type in _SCALAR_TYPES:
        return value

    # For containers, recursively unref their elements
    if np is not None and isinstance(value, np.ndarray):
        assert np is not None
        return np.array([deep_unref(item) for item in value]).reshape(value.shape) if value.dtype == object else value
    if value_type is list:
        return [deep_unref(item) for item in value]
    if value_type is tuple:
        return tuple(deep_unref(item) for item in value)
    if value_type is dict:
        return {deep_unref(k): deep_unref(v) for k, v in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, str):
        try:
            return type(value)(deep_unref(item) for item in value)  # pyright: ignore[reportCallIssue]
        except TypeError:
            return value

    return value


def as_rx[T](val: HasValue[T]) -> ReactiveValue[T]:
    """Normalize a value to a reactive object.

    If `val` is already reactive, it is returned unchanged. Otherwise a new
    [Signal][signified.Signal] is created wrapping the value.

    Args:
        val: Plain value or reactive value.

    Returns:
        A reactive value.
    """
    if _is_reactive_value(val):
        return val
    return Signal(cast(T, val))
