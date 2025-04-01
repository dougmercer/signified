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
    as_signal: Convert a value to a Signal if it's not already a reactive value.
    has_value: Type guard to check if an object has a value of a specific type.

Attributes:
    ReactiveValue: Union of Computed and Signal types.
    HasValue: Union of basic types and reactive types.
    NestedValue: Recursive type for arbitrarily nested reactive values.
"""

from .core import Computed, Signal, Variable
from .types import HasValue, NestedValue, ReactiveValue, has_value
from .utils import as_signal, computed, reactive_method, unref

__all__ = [
    "Variable",
    "Signal",
    "Computed",
    "computed",
    "reactive_method",
    "unref",
    "as_signal",
    "HasValue",
    "NestedValue",
    "ReactiveValue",
    "has_value",
]
