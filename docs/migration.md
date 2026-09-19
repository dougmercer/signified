# Migrating to 0.6

Version 0.6 replaces implicit deep behavior with explicit reads. Test both
returned values and propagation after updating nested values.

## Prepare on 0.5.1 first

Version 0.5.1 provides opt-in migration diagnostics, `deep_unref.register(Type)`,
and `rx.tap()` while retaining the previous following, equality, and scheduling
behavior. You can make these changes before upgrading the runtime:

- Enable migration diagnostics while exercising representative workflows.
- Read `source.value` explicitly when a computation should return its value.
- Call `deep_unref` inside callbacks that need resolved nested containers.
- Register custom containers with the one-argument `resolve(child)` handler API.
- Replace `rx.peek(fn)` with `rx.tap(fn)`; 0.5.1 keeps a deprecated alias.
- Route mutation through the Signal that owns the value.

`Binding`, `batch()`, and `untracked()` require 0.6. Change imports and replace
`Signal(source)` with `Binding(source)` when upgrading to that version.
Test propagation, callback counts, equality assumptions, and error recovery;
a warning-free run does not establish compatibility.

## Following versus storing

```python
from signified import Binding, Computed, Signal, unref

source = Signal(1)
# Use this when the old Signal(source) meant to follow the source:
following = Binding(source)
assert following.value == 1

# Store the wrapper itself when that is the intended data:
stored = Signal(source)
assert stored.value is source
assert unref(stored) is source  # one boundary only

# Explicit reads inside a computation create dependencies:
result = Computed(lambda: source.value * 2)
source.value = 2
assert result.value == 4
```

`Computed(lambda: source)` now returns the source object itself. `Binding`
follows one boundary too; following a source whose value is another reactive
object returns that object. Use `.rx.flatten()` for a consecutive chain of
wrappers or `deep_unref` for recursive container traversal.

Binding retains a stable identity while `.set(source)` or `.value = source`
selects another source. Assigning a plain value selects a private Signal.
Use `Signal[T]` for stored state, `Binding[T]` for a replaceable source, and
`ReactiveValue[T]` for the union of supported reactive wrappers.

## Container arguments and serialization

Old decorated functions recursively resolved container arguments. In 0.6,
`computed` and `effect` unwrap direct reactive arguments only. Read specific
leaves or explicitly resolve inside the callback:

```python
import json
from signified import Computed, Effect, Signal, deep_unref

values = [Signal(1), Signal(2)]
total = Computed(lambda: sum(deep_unref(values)))
assert total.value == 3
values[0].value = 10
assert total.value == 12

encoded = []
watcher = Effect(lambda: encoded.append(json.dumps(deep_unref(values))))
values[1].value = 20
assert json.loads(encoded[-1]) == [10, 20]
watcher.dispose()
```

Resolving *before* constructing the callback produces ordinary data and does
not subscribe that callback to the original leaves.

Keep using `deep_unref`; it is not deprecated. Use the same registered handler
API introduced in 0.5.1.

Unknown iterables are no longer reconstructed or consumed. Register an exact
custom type or project its fields into built-in containers. Numeric NumPy
arrays pass through; object-containing arrays are rebuilt. Results may still
share opaque objects with the input and are not guaranteed serializable.
Repeated references are resolved independently, and cyclic inputs eventually
raise `RecursionError`. Colliding keys/members raise instead of silently
discarding data.

## Equality and mutation

Containers, arrays, and user objects now compare by identity. Equal-but-distinct
replacements are stored and invalidate dependents. Exact built-in scalar values
compare by value (float NaNs count as unchanged); different types count as
changed. Unchanged assignments retain the previous stored object. Signified
never invokes arbitrary equality methods for change detection.

Effects now skip their callbacks when computed dependencies refresh to unchanged
outcomes, including when a Binding switches to an equal-valued source. Read the
original Signal too if the effect should react to changes that a derived value
intentionally filters out.

```python
from signified import Signal, computed

state = Signal({"a": 1})
result = computed(lambda data: data["a"])(state)
assert result.value == 1
state.value = {**state.value, "a": 2}
assert result.value == 2

state.value["a"] = 3  # raw mutation does not notify
state.update()        # explicit notification after in-place mutation
assert result.value == 3
```

Existing `state[key] = value` and forwarded attribute writes notify at the
wrapper level. Attribute writes are forwarded only by `Signal`; on a `Computed`
or `Binding` they raise `AttributeError`, as do names the wrapped object lacks.
They do not make every nested mutation or method call reactive. Reactive
containers are deferred beyond 0.6.

## Batch writes and untracked reads

```python
from signified import Effect, Signal, batch, untracked

x, y = Signal(1), Signal(2)
seen = []
watcher = Effect(lambda: seen.append((x.value, y.value)))
with batch():
    x.value = 10
    y.value = 20
assert seen == [(1, 2), (10, 20)]

with untracked():
    current = x.value
watcher.dispose()
```

Batch writes are immediate, while effects (including their first run) wait for
the outermost exit. Computed reads inside the block remain current. Cascading
effect writes can schedule more runs. No rollback, isolation, or async/thread
safety is provided. One failing effect raises directly; several failures in
one flush raise an `ExceptionGroup`, which `except*` can unpack. See the
[compute contract](compute-contract.md) for combined errors, recovery, and
lifetime rules.

Computed exceptions are now cached until a dependency changes or `invalidate()`
is called. Repeated reads re-raise without rerunning the callback. A new failed
evaluation and recovery both count as changed outcomes, so downstream callbacks
can catch errors and observe recovery even to the previous successful value.
Control-flow exceptions such as `KeyboardInterrupt` remain uncached.

`rx.peek(fn)`, deprecated in 0.5.1, is removed in 0.6; use `rx.tap(fn)`.
It is lazy and cached: the callback runs on evaluation, not on every cached
read. For a current value without subscribing, use `untracked()`.

## Optional migration diagnostics

Diagnostics are available in both 0.5.1 and 0.6. Enable them before exercising
representative application workflows:

```python
from signified import migration

migration.enable_warnings()
# Or: with migration.warnings(): ...
```

Alternatively set `SIGNIFIED_MIGRATION_WARNINGS=1` before import. To make the
migration warnings fail tests:

```bash
SIGNIFIED_MIGRATION_WARNINGS=1 pytest -W error::signified.migration.SignifiedMigrationWarning
```

Diagnostics detect recognized nested-reactive patterns in Signal values,
computed results, and ordinary container arguments to decorated functions.
Binding's internal source holder is excluded; normal Binding construction and
rebinding do not warn merely because they select a reactive source.
They do not read reactive values or consume arbitrary iterables. These are
heuristics: unknown types may hide affected values, and intentional storage of
reactive objects is valid even when migration mode warns. Disable migration
mode after reviewing those cases. Ordinary mutable containers do not warn.
Equality, scheduling, and forwarded writes require separate review.
