"""Type definitions for reactive programming."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Generic, TypeVar, Union

if sys.version_info >= (3, 12):
    from typing import TypeAliasType
else:
    from typing_extensions import TypeAliasType

if sys.version_info >= (3, 10):
    from typing import ParamSpec, TypeAlias, TypeGuard
else:
    from typing_extensions import ParamSpec, TypeAlias, TypeGuard

if TYPE_CHECKING:
    from .core import Computed, Signal

# Type variables
T = TypeVar("T")
Y = TypeVar("Y")
R = TypeVar("R")

A = TypeVar("A")
B = TypeVar("B")

P = ParamSpec("P")


class _HasValue(Generic[T]):
    """Class to make pyright happy with type inference."""

    @property
    def value(self) -> T: ...


NestedValue: TypeAlias = Union[T, "_HasValue[NestedValue[T]]"]
"""Recursive type hint for arbitrarily nested reactive values."""


ReactiveValue = TypeAliasType("ReactiveValue", Union["Computed[T]", "Signal[T]"], type_params=(T,))
"""A reactive object that would return a value of type T when calling unref(obj)."""

HasValue = TypeAliasType("HasValue", Union[T, "Computed[T]", "Signal[T]"], type_params=(T,))
"""This object would return a value of type T when calling unref(obj)."""


def has_value(obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check if an object has a value of a specific type."""
    from .utils import unref

    return isinstance(unref(obj), type_)
