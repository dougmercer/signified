# API reference

## Classes


::: signified.Signal
    options:
      members:
        - value
        - rx
        - with_name
        - at
        - update
        - __setattr__
        - __setitem__
        - __delitem__

::: signified.Computed
    options:
      members:
        - value
        - rx
        - with_name
        - invalidate

::: signified.Binding
    options:
      members:
        - value
        - source
        - set
        - derive
        - at
        - rx
        - with_name

::: signified.Effect
    options:
      members:
        - dispose

::: signified.Variable
    options:
      members: false

## The `rx` namespace {#reactive-namespace}

Every signal, computed value, and binding has an `rx` property. It holds
reactive versions of operations that Python syntax can't make reactive, such
as identity checks, membership, and choosing between two values:

::: signified._mixin._ReactiveNamespace
    options:
      show_root_heading: false
      members:
        - map
        - effect
        - tap
        - with_equal
        - len
        - is_
        - is_not
        - in_
        - contains
        - eq
        - ne
        - where
        - as_bool

## Operators {#magic-methods}

Arithmetic, comparisons, item access, attribute access, and calls on a reactive
value return a [Computed][signified.Computed] that follows its operands. The
[Operators](magic-methods.md) page gives an overview.

::: signified._mixin._ReactiveMixIn
    options:
      show_root_heading: false
      members:
        - __getattr__
        - __call__
        - __abs__
        - __round__
        - __ceil__
        - __floor__
        - __trunc__
        - __neg__
        - __pos__
        - __invert__
        - __add__
        - __radd__
        - __sub__
        - __rsub__
        - __mul__
        - __rmul__
        - __truediv__
        - __rtruediv__
        - __floordiv__
        - __rfloordiv__
        - __mod__
        - __rmod__
        - __pow__
        - __rpow__
        - __matmul__
        - __rmatmul__
        - __and__
        - __rand__
        - __or__
        - __ror__
        - __xor__
        - __rxor__
        - __lshift__
        - __rlshift__
        - __rshift__
        - __rrshift__
        - __divmod__
        - __rdivmod__
        - __lt__
        - __le__
        - __ge__
        - __gt__
        - __getitem__

## Functions

::: signified.computed
::: signified.effect
::: signified.unref
::: signified.has_value
::: signified.is_reactive
::: signified.as_rx
::: signified.batch
::: signified.untracked
::: signified.tracked_fields

## Nested values

::: signified.deep_unref
    options:
      show_attribute_values: false

::: signified.ResolveContext
    options:
      members: false

[Resolving nested values](resolution.md) has examples of custom handlers.

## Types

### HasValue {#signified.HasValue}

`HasValue[T]` is `T | Computed[T] | Signal[T] | Binding[T]`: a plain or
reactive value that resolves to `T`. Use it to annotate a parameter that
accepts either.

### ReactiveValue {#signified.ReactiveValue}

`ReactiveValue[T]` is `Computed[T] | Signal[T] | Binding[T]`: a reactive value
that resolves to `T`.
