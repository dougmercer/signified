"""Type definitions for reactive programming."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._reactive import Binding, Computed, Signal

__all__ = ["HasValue", "ReactiveValue"]

type ReactiveValue[T] = Computed[T] | Signal[T] | Binding[T]
"""A reactive object that would return a value of type T when calling unref(obj)."""

type HasValue[T] = T | ReactiveValue[T]
"""This object would return a value of type T when calling unref(obj)."""
