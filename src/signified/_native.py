"""Public-shaped reactive classes over the Rust core.

`Signal` and `Computed` here subclass the native base classes in
`signified._core` together with the existing `_ReactiveMixIn`, which keeps the
operators, attribute proxy, `.rx` namespace, and typing in Python. Nothing in
the public package imports this module yet.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Callable

from . import _core
from ._functions import unref
from ._mixin import _ReactiveMixIn

__all__ = ["Signal", "Computed", "computed_call", "untracked"]


class Signal[T](_core.Signal, _ReactiveMixIn[T]):
    """Mutable state backed by the Rust engine."""

    __slots__ = ()

    def __setattr__(self, name: str, value: Any) -> None:
        """Forward a public attribute write to the wrapped object and notify."""
        if name == "value" or name[:1] == "_" or hasattr(type(self), name):
            object.__setattr__(self, name, value)
            return
        wrapped = self._value
        if not hasattr(wrapped, name):
            raise AttributeError(f"'{type(wrapped).__name__}' object has no attribute '{name}'")
        setattr(wrapped, name, value)
        self.update()


class Computed[T](_core.Computed, _ReactiveMixIn[T]):
    """Derived value backed by the Rust engine."""

    __slots__ = ()


def computed_call[R](func: Callable[..., R], *args: Any, **kwargs: Any) -> Computed[R]:
    """Build an operator node; mirrors `signified._functions._computed_call`."""
    if kwargs:

        def call() -> R:
            return func(*[unref(arg) for arg in args], **{key: unref(value) for key, value in kwargs.items()})

        return Computed(call)
    return Computed(func, _op_args=args)


@contextmanager
def untracked() -> Generator[None, None, None]:
    """Read without subscribing the enclosing computation."""
    _core.push_untracked()
    try:
        yield
    finally:
        _core.pop_untracked()


_core._register_standard_types([Signal, Computed])
