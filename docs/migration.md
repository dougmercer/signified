# Migrating to 0.6

Version 0.6 makes you choose when to read nested reactive values. Check both
results and what happens after inputs change when upgrading.

## Prepare on 0.5.1 first

You can make these changes before upgrading:

- Enable [migration warnings](#optional-migration-diagnostics) while exercising
  representative workflows.
- Read `.value` when a function should return a reactive object's current value.
- Call `deep_unref` inside callbacks that need values from nested containers.
- Register custom containers with `deep_unref.register(Type)`.
- Replace `rx.peek(fn)` with `rx.tap(fn)`.
- Make changes through the `Signal` that owns the value.

`Binding`, `batch()`, and `untracked()` require 0.6. Version 0.5.1 still uses
the earlier following, equality, and effect timing rules. Test those behaviors
again after upgrading, even if no migration warnings appear.

## Following versus storing

Replace `Signal(source)` with `Binding(source)` when the outer object should
follow another signal's value:

```python
from signified import Binding, Signal

source = Signal(1)
# Before 0.6: selected = Signal(source)
selected = Binding(source)
source.value = 2
assert selected.value == 2
```

In 0.6, `Signal(source)` stores the source object itself. Likewise,
`Computed(lambda: source)` returns that object. Change it to
`Computed(lambda: source.value)` to calculate from its current value.

`unref` and `Binding` read one reactive object at a time. If that object's value
is another reactive object, it is returned as-is. For more on replacing sources,
see [Binding](usage.md#replacing-a-reactive-source-with-binding).

## Container arguments and serialization

Decorated functions previously resolved reactive values inside container
arguments for you. Move that work inside the function:

```python
from signified import Signal, computed, deep_unref

values = [Signal(1), Signal(2)]
# Before 0.6: total = computed(sum)(values)
total = computed(lambda items: sum(deep_unref(items)))(values)
assert total.value == 3
values[0].value = 10
assert total.value == 12
```

Direct reactive arguments are still read automatically. `deep_unref` remains
supported, with the handler API introduced in 0.5.1. Calling it before creating
the computation does not make that computation follow the original inputs.

Unregistered iterables now pass through unchanged. Register your exact custom
type if you need its contents resolved. Colliding keys or set members now raise
an error instead of silently losing data. See [Nested values](resolution.md)
for registration, JSON, supported containers, and copying limits.

## Equality and mutation

Review code that relied on equal lists, dictionaries, or arrays suppressing
updates. These now compare by object identity, so a new object counts as a
change even if its contents are equal. Exact built-in scalar values still
compare by value; see the [full equality rules](compute-contract.md#what-counts-as-a-change).

Effects can now skip running when their calculated inputs return unchanged
results, including when a binding switches to an equal-valued source. If an
effect must react to the original signal's changes, read that signal as well.

Only `Signal` forwards attribute and item writes. Change the owning signal
instead of writing through a `Computed` or `Binding`. Unknown attribute names
now raise `AttributeError`. Raw object changes still need an explicit
`.update()`; see [Lists and dictionaries](usage.md#collections-and-item-assignment).

## Batch writes and untracked reads

Review code that assumes effects run once per write, in a fixed order, or
again after every failed read:

- `batch()` defers effects until its outermost block exits, including the first
  run of an effect created inside the block. Writes are still immediate.
- One effect can cause further runs by changing another value. Batching does
  not undo writes on error or provide thread safety.
- A `Computed` now saves an ordinary exception until an input changes or
  `.invalidate()` is called. Repeated reads raise the same saved error without
  rerunning the function. New failed evaluations and recovery count as changes.
- Other pending effects continue after an ordinary effect failure. Multiple
  failures are raised together as an `ExceptionGroup`; use `except*` to handle
  them when needed.

See [How updates work](compute-contract.md#batching-and-effect-lifetime) for
lifetime, error recovery, and combined batch errors.

`rx.peek(fn)` is removed. Use `rx.tap(fn)` to inspect a calculation when it runs,
or `untracked()` to read without adding a dependency. `tap` saves its result
and skips unread intermediate values; it is not an automatic effect.

## Optional migration diagnostics

Warnings are available in both 0.5.1 and 0.6:

```python
from signified import migration

migration.enable_warnings()
# Or wrap the code being checked in: with migration.warnings():
```

You can also set `SIGNIFIED_MIGRATION_WARNINGS=1` before import. To make warnings
fail your tests:

```bash
SIGNIFIED_MIGRATION_WARNINGS=1 pytest -W error::signified.migration.SignifiedMigrationWarning
```

Warnings look for nested reactive values stored in signals, returned from
computations, or passed in containers to decorated functions. They do not
read reactive values or consume arbitrary iterables. Normal binding creation
and source changes do not warn simply because they select a reactive source.

Warnings cannot find every affected case: unknown objects can hide reactive
values, and intentionally storing a signal can still trigger a warning.
Ordinary mutable containers alone do not warn. Review equality, effect timing,
and forwarded writes separately, and disable warnings once the review is done.
