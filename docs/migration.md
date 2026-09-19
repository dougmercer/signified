# Preparing for 0.6

Version 0.5.1 is the transition release. It retains implicit following, recursive
decorator arguments, and the existing equality and effect behavior. It adds
migration diagnostics, custom resolver registration, and `rx.tap()` so you can
prepare before upgrading to 0.6.

## Changes you can make on 0.5.1

### Enable migration diagnostics

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

Diagnostics recognize reactive values stored inside Signals, returned from
computations, or passed inside ordinary container arguments to decorated
functions. They do not change runtime resolution or propagation. Diagnostics
themselves do not evaluate reactive values or consume unknown iterables; the
legacy runtime still performs its usual reads and traversal afterward.

These are heuristics. Unknown types may hide affected values, and intentional
storage of reactive objects can warn too. Equality, scheduling, and forwarded
writes need separate review; a warning-free run is not proof of compatibility.

### Use explicit reads and resolution

Return `source.value` when a computation should return the current value of a
source. Resolve nested containers inside the callback that should subscribe to
their contents. These patterns work in both releases:

```python
from signified import Computed, Signal, deep_unref

source = Signal(1)
following = Computed(lambda: source.value)
values = [source, Signal(2)]
total = Computed(lambda: sum(deep_unref(values)))

source.value = 3
assert following.value == 3
assert total.value == 5
```

Resolving before constructing the callback does not subscribe that callback to
the original leaves. Test propagation after updates as well as initial values.

### Register custom containers

Use `@deep_unref.register(MyType)` and the supplied one-argument `resolve(child)`
function. The handler API is the same in 0.5.1 and 0.6. See
[Resolving nested values](resolution.md) for examples.

Unregistered iterable reconstruction still works in 0.5.1 with a
`DeprecationWarning`. In 0.6, unknown types and unregistered subclasses pass
through unchanged without inspection or iteration. `deep_unref` remains
supported; explicit resolution is the migration path.

### Rename `peek` calls to `tap`

Replace `rx.peek(callback)` with `rx.tap(callback)`. Version 0.5.1 retains
`peek` as a deprecated alias; 0.6 removes it. Both names in 0.5.1 create the
same lazy, cached computation. The callback runs on evaluation, not on every
cached read. Neither is an untracked getter.

### Review mutation and equality assumptions

Make writes through the Signal that owns the value. Item and attribute writes
through Computed values will be rejected in 0.6. Raw in-place mutations through
`.value` require `Signal.update()` to notify dependents in either release.

In 0.6, exact built-in scalars compare by value and other objects compare by
identity. Equal-but-distinct containers will therefore trigger changes, while
assigning the same object will not. Different scalar types count as changed.
Review effects that depend on equality suppression or custom equality methods.

## Changes that require 0.6

`Binding`, `batch()`, and `untracked()` are available starting in 0.6. Do not
import them while the application still needs to run on 0.5.1.

When upgrading, replace `Signal(source)` with `Binding(source)` wherever the
outer handle should follow a replaceable source. In 0.6, `Signal(source)`
stores the reactive object itself, `Computed(lambda: source)` returns it, and
`unref` crosses just one reactive boundary. Containers stored in Signals no
longer forward their children's updates automatically.

Decorated `computed` and `effect` functions will unwrap only direct reactive
arguments. Use the explicit reads and `deep_unref` calls above for nested data.

Version 0.6 also changes effect scheduling and error recovery. Notification
waves invalidate dependencies before effects run; `batch()` defers and
coalesces effects. Effects skip callbacks when computed inputs refresh to
unchanged outcomes. Failed runs retain the dependencies they read, and
Computed exceptions are cached until an input changes or `invalidate()` is
called. Test callback counts, error handling, and recovery during the upgrade.
