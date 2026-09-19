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
    is_reactive: Type guard to check if an object is a reactive wrapper.
    deep_unref: Explicit recursive resolution through registered types.
    batch: Defer effects across multiple writes.
    untracked: Read without subscribing the enclosing consumer.
    migration: Opt-in diagnostics for behavior changed in 0.6.

Attributes:
    ReactiveValue: Union of Signal, Computed, and Binding types.
    HasValue: Union of basic types and reactive types.
"""

# Import _mixin first to initialize _ReactiveMixIn before runtime classes.
from . import _mixin, migration
from ._functions import as_rx, computed, effect, has_value, unref
from ._reactive import Binding, Computed, Effect, Signal, Variable, is_reactive, untracked
from ._resolve import ResolveContext, deep_unref
from ._scheduler import batch
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
    "is_reactive",
    "deep_unref",
    "ResolveContext",
    "batch",
    "untracked",
    "migration",
]
