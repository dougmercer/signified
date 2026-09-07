"""Function helpers for :mod:`signified` reactive objects."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeGuard, overload

from ._reactive import Computed, Effect, Signal, is_reactive, _track_read
from ._types import HasValue, ReactiveValue

_PLAIN_ARG_TYPES = {int, float, str, bool, bytes, complex, type(None)}


def _identity[T](value: T) -> T:
    return value


def _get_unref_op(value: Any) -> Callable[[Any], Any]:
    if is_reactive(value):
        return unref
    if type(value) in _PLAIN_ARG_TYPES:
        return _identity
    return deep_unref


def _bind_args[R](func: Callable[..., R], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Callable[[], R]:
    """Return a zero-argument callable that resolves `args`/`kwargs` and calls `func`.

    Each argument's resolver is chosen once, from the shape of the outer
    argument, and reused on every evaluation: reactive values use
    [unref][signified.unref], exact plain scalars pass through unchanged, and
    everything else uses [deep_unref][signified.deep_unref].
    """
    if not kwargs:
        if not args:
            return func
        if len(args) == 1:
            arg = args[0]
            resolve_arg = _get_unref_op(arg)
            return lambda: func(resolve_arg(arg))
        if len(args) == 2:
            left, right = args
            resolve_left = _get_unref_op(left)
            resolve_right = _get_unref_op(right)
            return lambda: func(resolve_left(left), resolve_right(right))

    arg_resolvers = tuple(_get_unref_op(arg) for arg in args)
    kw_resolvers = {key: _get_unref_op(value) for key, value in kwargs.items()}

    def call() -> R:
        resolved_args = tuple(resolver(arg) for resolver, arg in zip(arg_resolvers, args, strict=False))
        resolved_kwargs = {key: kw_resolvers[key](value) for key, value in kwargs.items()}
        return func(*resolved_args, **resolved_kwargs)

    return call


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
        return Computed(_bind_args(func, args, kwargs))

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
        return Effect(_bind_args(func, args, kwargs))

    return wrapper


@overload
def unref[T](value: HasValue[T]) -> T: ...


@overload
def unref[T, U](value: HasValue[T] | HasValue[U]) -> T | U: ...


def unref(value: Any) -> Any:
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
    while is_reactive(current):
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


@overload
def as_rx[T](val: HasValue[T]) -> ReactiveValue[T]: ...


@overload
def as_rx[T, U](val: HasValue[T] | HasValue[U]) -> ReactiveValue[T] | ReactiveValue[U]: ...


def as_rx(val: Any) -> ReactiveValue[Any]:
    """Normalize a value to a reactive object.

    If `val` is already reactive, it is returned unchanged. Otherwise a new
    [Signal][signified.Signal] is created wrapping the value.

    Args:
        val: Plain value or reactive value.

    Returns:
        A reactive value.
    """
    if is_reactive(val):
        return val
    return Signal(val)


# Loaded after unref is defined to avoid an import cycle.
from ._resolve import deep_unref  # noqa: E402
