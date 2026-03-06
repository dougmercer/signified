"""A reactive programming library for creating and managing reactive values and computations.

This module provides tools for building reactive systems, where changes in one value
automatically propagate to dependent values.

Classes:
    Variable: Abstract base class for reactive values.
    Signal: A container for mutable reactive values.
    Computed: A container for computed reactive values (from functions).

Functions:
    unref: Dereference a potentially reactive value.
    computed: Decorator to create a reactive value from a function.
    reactive_method: Decorator to create a reactive method.
    as_rx: Convert a value to a reactive value if it's not already reactive.
    as_signal: Deprecated alias for as_rx.
    has_value: Type guard to check if an object has a value of a specific type.

Attributes:
    ReactiveValue: Union of Computed and Signal types.
    HasValue: Union of basic types and reactive types.
"""

# Import _mixin first to initialize _ReactiveMixIn before runtime classes.
from . import _mixin
from ._functions import as_rx, as_signal, computed, deep_unref, has_value, reactive_method, unref
from ._reactive import Computed, Effect, Signal, Variable
from ._types import HasValue, ReactiveValue

del _mixin

__all__ = [
    "Variable",
    "Signal",
    "Computed",
    "Effect",
    "computed",
    "reactive_method",
    "unref",
    "as_rx",
    "as_signal",
    "HasValue",
    "ReactiveValue",
    "has_value",
    "deep_unref",
]
