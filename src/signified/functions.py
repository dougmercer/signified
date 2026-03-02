"""Function helpers for :mod:`signified` reactive objects."""

from __future__ import annotations

import importlib.util
import warnings
from collections.abc import Iterable
from functools import wraps
from typing import Any, Callable, Concatenate, TypeGuard, cast

from .reactive_objects import Computed, Signal, Variable, _track_read
from .types import HasValue

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None  # User does not have numpy installed


def computed[R](func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Wrap a function so calls produce a reactive ``Computed`` result.

    The returned wrapper accepts plain values, reactive values, or nested
    containers that include reactive values. On each recomputation, arguments
    are normalized with :func:`deep_unref`, so ``func`` receives plain Python
    values.

    The created :class:`Computed` tracks dependencies dynamically while the
    wrapped function runs. Any reactive value read during evaluation becomes a
    dependency for subsequent updates.

    Args:
        func: Function that computes a derived value from its inputs.

    Returns:
        A wrapper that returns a :class:`Computed` when called.
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
    """Resolve a value by unwrapping reactive containers until plain data remains.

    This utility repeatedly unwraps :class:`Variable` objects by following
    their ``.value`` chain. When called inside a :class:`Computed` or
    :class:`Effect` evaluation, each unwrapped reactive is registered as a
    dependency so that changes propagate correctly — the same behaviour as
    reading ``.value`` directly.

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


# ---------------------------------------------------------------------------
# Utility functions that depend on the reactive types above
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
