"""Utility functions for reactive programming."""

from __future__ import annotations

import importlib.util
import sys
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Iterable, cast

from .types import HasValue, P, R, T

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if HAS_NUMPY:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None  # User doesn't have numpy installed


if sys.version_info >= (3, 10):
    from typing import Concatenate
else:
    from typing_extensions import Concatenate

if TYPE_CHECKING:
    from .core import Computed, Signal


def unref(value: HasValue[T]) -> T:
    """Dereference a value, resolving any nested reactive variables."""
    # Imported locally to avoid circular imports
    from .core import Variable

    while isinstance(value, Variable):
        value = value._value
    return cast(T, value)


def deep_unref(value: Any) -> Any:
    """Recursively `unref` values potentially within containers."""
    # Imported locally to avoid circular imports
    from .core import Variable

    # Base case - if it's a reactive value, unref it
    if isinstance(value, Variable):
        return deep_unref(unref(value))

    # For containers, recursively unref their elements
    if HAS_NUMPY and isinstance(value, np.ndarray):  # pyright: ignore[reportOptionalMemberAccess]
        assert np is not None
        return np.array([deep_unref(item) for item in value]).reshape(value.shape) if value.dtype == object else value
    if isinstance(value, dict):
        return {deep_unref(unref(k)): deep_unref(unref(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(deep_unref(item) for item in value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        try:
            return type(value)(deep_unref(item) for item in value)  # pyright: ignore[reportCallIssue]
        except TypeError:
            # This is not some plain old iterable initialized by *args. Just return as-is
            return value

    # For non-containers/non-reactive values, return as-is
    return value


def computed(func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Decorate the function to return a reactive value."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        # Import here to avoid circular imports
        from .core import Computed

        def compute_func() -> R:
            resolved_args = tuple(deep_unref(arg) for arg in args)
            resolved_kwargs = {key: deep_unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func, (*args, *kwargs.values()))

    return wrapper


# Note: `Any` is used to handle `self` in methods.
InstanceMethod = Callable[Concatenate[Any, P], T]
ReactiveMethod = Callable[Concatenate[Any, P], "Computed[T]"]


def reactive_method(*dep_names: str) -> Callable[[InstanceMethod[P, T]], ReactiveMethod[P, T]]:
    """Decorate the method to return a reactive value."""

    def decorator(func: InstanceMethod[P, T]) -> ReactiveMethod[P, T]:
        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Computed[T]:
            # Import here to avoid circular imports
            from .core import Computed

            object_deps = [getattr(self, name) for name in dep_names if hasattr(self, name)]
            all_deps = (*object_deps, *args, *kwargs.values())
            return Computed(lambda: func(self, *args, **kwargs), all_deps)

        return wrapper

    return decorator


def as_signal(val: HasValue[T]) -> Signal[T]:
    """Convert a value to a Signal if it's not already a reactive value."""
    # Import here to avoid circular imports
    from .core import Signal, Variable

    return cast(Signal[T], val) if isinstance(val, Variable) else Signal(val)
