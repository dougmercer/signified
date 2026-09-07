# Migrating to 0.6

Version 0.6 replaces implicit deep behavior with explicit reads. Test both
returned values and propagation after updating nested values.

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
object returns that object. Use explicit `.value` reads to follow additional
boundaries, or `deep_unref` for recursive container traversal.

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

Keep using `deep_unref`; it is not deprecated. The development-only `deep`
namespace and its decorators are removed. Replace `deep.unref(x)` with
`deep_unref(x)`, `deep.register(T)` with `deep_unref.register(T)`, and deep
decorators with an explicit resolver call inside a normal callback.

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
wrapper level. They do not make every nested mutation or method call reactive.
Reactive containers are deferred beyond 0.6.

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
safety is provided. Single batch flush failures now use `ExceptionGroup`; use
`except*` to handle individual error types. See the [compute contract](compute-contract.md)
for combined errors, recovery, and lifetime rules.

`.rx.peek(callback)` is lazy and cached: the callback runs on evaluation,
not on every cached read. For a current value without subscribing, use
`untracked()`.

## Optional migration diagnostics

Enable diagnostics before exercising representative application workflows:

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
They do not read reactive values or consume arbitrary iterables. These are
heuristics: unknown types may hide affected values, and intentional storage of
reactive objects is valid even when migration mode warns. Disable migration
mode after reviewing those cases. Ordinary mutable containers do not warn.
