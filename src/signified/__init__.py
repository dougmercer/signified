"""A reactive programming library for creating and managing reactive values and computations.

This module provides tools for building reactive systems, where changes in one value
automatically propagate to dependent values.

Classes:
    Variable: Abstract base class for reactive values.
    Signal: A container for mutable values.
    Computed: A container for values derived from functions.
    Binding: A stable reactive handle whose source can be replaced.

Functions:
    unref: Dereference a potentially reactive value.
    computed: Decorator to create a reactive value from a function.
    as_rx: Convert a value to a reactive value if it's not already reactive.
    has_value: Type guard to check if an object has a value of a specific type.
    deep: Explicit recursive unref, computed, and effect helpers.

Attributes:
    ReactiveValue: Union of Signal, Computed, and Binding types.
    HasValue: Union of basic types and reactive types.
"""

# Import _mixin first to initialize _ReactiveMixIn before runtime classes.
from . import _mixin, deep
from ._functions import as_rx, computed, deep_unref, effect, has_value, unref
from ._reactive import Binding, Computed, Effect, Signal, Variable
from ._types import HasValue, ReactiveValue

del _mixin

__all__ = [
    "Variable",
    "Signal",
    "Computed",
    "Binding",
    "Effect",
    "computed",
    "effect",
    "unref",
    "as_rx",
    "HasValue",
    "ReactiveValue",
    "has_value",
    "deep_unref",
    "deep",
]
