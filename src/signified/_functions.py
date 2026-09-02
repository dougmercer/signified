"""Function helpers for :mod:`signified` reactive objects."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeGuard, cast
from warnings import warn

from ._reactive import Computed, Effect, Signal, _is_reactive_value, _track_read
from ._types import HasValue, ReactiveValue


def _bind_args[R](func: Callable[..., R], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Callable[[], R]:
    """Return a zero-argument callable that resolves `args`/`kwargs` and calls `func`.

    Direct reactive arguments are shallowly unwrapped on every evaluation.
    Plain values, including containers with reactive descendants, pass through
    unchanged.
    """
    if not kwargs:
        if not args:
            return func
        if len(args) == 1:
            arg = args[0]
            return lambda: func(unref(arg))
        if len(args) == 2:
            left, right = args
            return lambda: func(unref(left), unref(right))

    def call() -> R:
        resolved_args = tuple(unref(arg) for arg in args)
        resolved_kwargs = {key: unref(value) for key, value in kwargs.items()}
        return func(*resolved_args, **resolved_kwargs)

    return call


def computed[R](func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Wrap a function so calls produce a reactive [Computed][signified.Computed] result.

    Direct reactive arguments are shallowly unwrapped on each recomputation.
    Plain values, including containers that contain reactive values, are passed
    through unchanged. Use [deep.computed][signified.deep.computed] for explicit
    recursive argument resolution.

    Any reactive value read during evaluation becomes a dependency; the
    [Computed][signified.Computed] updates automatically when any dependency changes.

    Args:
        func: Function that computes a derived value from its inputs.

    Returns:
        A wrapper that returns a [Computed][signified.Computed] when called.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        return Computed(_bind_args(func, args, kwargs))

    return wrapper


def effect(func: Callable[..., None]) -> Callable[..., Effect]:
    """Wrap a function so calls produce a reactive [Effect][signified.Effect].

    Direct reactive arguments are shallowly unwrapped on each re-run. Plain
    values, including containers that contain reactive values, are passed
    through unchanged. Use [deep.effect][signified.deep.effect] for explicit
    recursive argument resolution.

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
        return Effect(_bind_args(func, args, kwargs))

    return wrapper


def unref[T](value: HasValue[T]) -> T:
    """Unwrap exactly one reactive boundary.

    When called inside a [Computed][signified.Computed] or [Effect][signified.Effect]
    evaluation, the reactive registers as a dependency — equivalent to reading
    `.value` directly.

    Args:
        value: Plain value or reactive value.

    Returns:
        The value inside one reactive wrapper, or the original plain value.

    Example:
        ```py
        >>> source = Signal(5)
        >>> unref(source)
        5

        ```
    """
    if not _is_reactive_value(value):
        return cast(T, value)
    if value._IS_COMPUTED:
        value._impl.ensure_uptodate()
    _track_read(value)
    return cast(T, value._value)


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


def deep_unref(value: Any) -> Any:
    """Deprecated alias for [deep.unref][signified.deep.unref]."""
    warn("deep_unref() is deprecated; use deep.unref()", DeprecationWarning, stacklevel=2)
    from .deep import unref as deep_unwrap

    return deep_unwrap(value)


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
