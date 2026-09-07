# Compute contract

> **Dependencies come from reactive reads, not containment.**

`Signal[T]` stores a value. `Computed[T]` lazily evaluates and caches a result.
`Binding[T]` follows an explicitly selected source while retaining a stable
identity. Reactive objects are ordinary Python values: storing or returning one
is valid and does not implicitly follow it.

```python
from signified import Binding, Computed, Signal, unref

inner = Signal(1)
outer = Signal(inner)
assert outer.value is inner
assert unref(outer) is inner
assert Computed(lambda: inner).value is inner
assert Binding(inner).value == 1
assert Binding(outer).value is inner
```

## Reads and equality

`unref` crosses exactly one boundary. `computed` and `effect` unwrap only direct
reactive arguments, once per evaluation. Plain arguments, including containers,
pass through unchanged.

```python
from signified import Signal, computed

x = Signal(2)
config = {"x": x}

@computed
def double(config):
    return config["x"].value * 2

result = double(config)
assert result.value == 4
x.value = 3
assert result.value == 6
```

Only the read of `x.value` establishes that dependency. Merely returning
`config` would not. Computed callbacks should be pure; perform mutations in
application code or effects. A computed's read-only property does not freeze
its returned Python object.

Signal assignments and computed results use the same equality policy:

- Exact built-in `int`, `bool`, `str`, `bytes`, `complex`, `NoneType`, and `float`
  compare by value. Two float NaNs count as unchanged.
- Different types count as changed, including `1` versus `True`.
- All other values, including containers, arrays, and user objects, compare by
  identity. Signified does not call their equality methods.
- Unchanged assignments/results retain the previous stored object.

A distinct but equal dictionary therefore replaces its predecessor and
invalidates dependents. Mutating an existing dictionary through `.value` does
not notify; use replacement or call `Signal.update()` after mutation. Existing
wrapper item/attribute assignments also notify, but are not general mutation
observation. Mutations through aliases remain invisible.

## Recursive resolution and serialization

`deep_unref` recursively reads reactive values through registered exact types.
It rebuilds lists, tuples, dictionaries (including keys), sets, frozensets, and
deques. With NumPy installed, exact arrays containing Python objects are rebuilt
with their shape and dtype preserved; numeric arrays pass through unchanged.

```python
import json
from signified import Effect, Signal, deep_unref

x, y = Signal(1), Signal(2)
payload = {"position": [x, y]}
encoded = json.dumps(deep_unref(payload))
assert json.loads(encoded) == {"position": [1, 2]}

# Resolve inside the callback to subscribe to the reached leaves.
sent = []
watcher = Effect(lambda: sent.append(deep_unref(payload)))
x.value = 3
assert sent[-1] == {"position": [3, 2]}
watcher.dispose()
```

For application objects, explicitly project the fields you want to serialize.
The serializer remains responsible for dates, domain objects, and format rules.

Unknown types and subclasses pass through by identity without inspection or
iteration. They may hide unresolved reactive values. The result is not
necessarily serializable or detached, and traversal is not a globally atomic
snapshot. Register an exact custom type when reusable resolution is needed:

```python
from signified import ResolveContext, Signal, deep_unref

class Box:
    def __init__(self, child):
        self.child = child

@deep_unref.register(Box)
def resolve_box(box: Box, resolve: ResolveContext) -> Box:
    return Box(resolve(box.child, ".child"))

assert deep_unref(Box(Signal(1))).child == 1
```

A handler defines which children are reached; use its callback on each intended
child. Registrations replace any previous handler for that exact type. Return
types can change, so general `deep_unref` results are typed as `Any`.

Aliases among traversed objects are preserved. All encountered cycles raise
`ValueError`. Resolved dictionary keys or set members that collide raise
`ValueError`; unhashable resolved keys/members raise `TypeError`. Diagnostics
identify traversal locations. Handler failures propagate with path notes rather
than falling back silently. Unknown objects and references inside them remain
untouched.

## Untracked reads

```python
from signified import Computed, Effect, Signal, deep_unref, untracked

trigger, other = Signal(0), Signal(1)
derived = Computed(lambda: other.value * 2)
seen = []

def observe():
    current = trigger.value
    with untracked():
        seen.append((current, derived.value, deep_unref([other])))

watcher = Effect(observe)
other.value = 2
assert len(seen) == 1
trigger.value = 1
assert seen[-1] == (1, 4, [2])
watcher.dispose()
```

`untracked()` suppresses subscriptions of the enclosing consumer. Nested
computations still collect their own dependencies and refresh normally. Reads,
plugin hooks, errors, and writes are not suppressed. Scopes nest and restore
tracking even on exceptions.

`rx.peek(fn)` creates a lazy cached computation that invokes a callback and
passes through the source value. It skips unread intermediate updates and does
not repeat its callback on cached reads. It is not an untracked getter.

## Batching and effect lifetime

```python
from signified import Computed, Effect, Signal, batch

x, y = Signal(1), Signal(2)
total = Computed(lambda: x.value + y.value)
seen = []
watcher = Effect(lambda: seen.append(total.value))
with batch():
    x.value = 10
    assert total.value == 12
    y.value = 20
    assert seen == [3]
assert seen == [3, 30]
watcher.dispose()
```

Writes and invalidation happen immediately. Effects, including newly created
ones, wait until the outermost batch exits. Outside batches, effects run
synchronously after the current notification wave has invalidated the graph.
Pending notifications combine into the next run. Later writes from another
effect may cause another run in the same flush; do not assume independent
callback order or at-most-once execution.

Retain each Effect while it should remain active. The queue does not own it.
`dispose()` is idempotent and cancels pending work, including when called from
inside its callback. An effect created in a batch and discarded before exit
may never execute.

Batching provides no rollback or isolated reads. Ordinary code can see
intermediate state, and applied writes are flushed even when the body raises.

### Errors and recovery

A failed effect retains the dependencies from its last successful run. A later
change to one of them retries it. New dependencies read only during a failed
branch are not retained. A failed first execution has no successful dependency
set and therefore no automatic retry subscription.

Healthy pending effects continue after ordinary callback failures. An explicit
batch reports flush errors in an `ExceptionGroup`, even for one failure. A body
error alone is re-raised unchanged; simultaneous body and flush failures are
grouped together (using `BaseExceptionGroup` when necessary). Outside explicit
batches, a single callback failure propagates directly, while multiple failures
are grouped.

Control-flow exceptions such as `KeyboardInterrupt` abort flushing and clear
pending work. Active subscriptions remain eligible for future updates. Feedback
that exceeds 100 runs of one effect per flush raises `RuntimeError` through the
same error-reporting mechanism and clears remaining pending work.

All reactive operations are single-threaded and synchronous. Neither `batch()`
nor `untracked()` may span `await`.
