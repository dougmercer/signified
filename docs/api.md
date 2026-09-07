---
hide:
  - navigation
---
# API Reference

## Classes


::: signified.Signal
    options:
      members:
        - value
        - rx
        - with_name
        - at

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

## Reactive Namespace

The `rx` property on any reactive value exposes a namespace of additional
operations — reactive equivalents of things Python's dunder protocol cannot
return as reactive values (identity checks, containment, ternary, etc.):

::: signified._mixin._ReactiveNamespace
    options:
      show_root_heading: false
      members:
        - map
        - effect
        - peek
        - len
        - is_
        - is_not
        - in_
        - contains
        - eq
        - where
        - as_bool

## Magic Methods

Reactive values support Python's operator protocol. Arithmetic, comparison,
subscript, and attribute-access operations all return reactive
[Computed][signified.Computed] values derived from their operands.

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
        - __and__
        - __rand__
        - __or__
        - __ror__
        - __xor__
        - __rxor__
        - __lshift__
        - __rshift__
        - __divmod__
        - __rdivmod__
        - __lt__
        - __le__
        - __ge__
        - __gt__
        - __ne__
        - __getitem__
        - __setattr__
        - __setitem__

## Functions

::: signified.computed
::: signified.effect
::: signified.unref
::: signified.has_value
::: signified.is_reactive
::: signified.as_rx
::: signified.batch
::: signified.untracked

## Explicit deep resolution {#signified.deep_unref}

Use `deep_unref(value)` to replace reactive values inside supported containers.
For example, `deep_unref({"x": Signal(1)})` returns `{"x": 1}`. To support a
custom object, register a handler with `@deep_unref.register(MyType)`.

::: signified._resolve._DeepUnref
    options:
      show_root_heading: false
      members:
        - __call__
        - register

::: signified.ResolveContext
    options:
      members:
        - __call__

See [Resolving nested values](resolution.md) for custom-handler examples.

## Migration diagnostics

Import the namespace with `from signified import migration`.

::: signified.migration.enable_warnings
::: signified.migration.disable_warnings
::: signified.migration.warnings
::: signified.migration.warnings_enabled
::: signified.migration.SignifiedMigrationWarning

## Types

### HasValue {#signified.HasValue}

**`HasValue[T]`** — `T | Computed[T] | Signal[T] | Binding[T]`

A plain or reactive value that resolves to `T`. Use as a type hint when a
parameter accepts either a raw value or a reactive wrapper.

### ReactiveValue {#signified.ReactiveValue}

**`ReactiveValue[T]`** — `Computed[T] | Signal[T] | Binding[T]`

A reactive wrapper that resolves to `T`.
