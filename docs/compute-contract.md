# Compute contract

> **Dependencies come from reactive reads, not containment.**

`Signal[T]` stores a value. `Computed[T]` lazily evaluates and caches a value or
an exception. `Effect` runs a callback when its tracked inputs change.
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

Operators and decorated functions follow the same one-boundary rule. Applying
an operator to a `Signal` that stores a reactive value produces a computation
over that reactive value, not over the number inside it:

```python
from signified import Binding, Signal

inner = Signal(2)
outer = Signal(inner)
nested = outer + 1
assert nested.value.value == 3   # nested.value is a Computed, not 3

following = Binding(inner) + 1
assert following.value == 3      # Binding reads through to the number
```

Before 0.6, `Signal(inner) + 1` resolved to `3`. Use `Binding(inner)` when the
outer handle should follow the inner value.

## Reads and equality

`unref` crosses exactly one boundary. `computed` and `effect` unwrap only direct
reactive arguments, once per evaluation. Plain arguments, including containers,
pass through unchanged. `.rx.flatten()` explicitly follows a consecutive chain
of wrappers while leaving containers opaque.

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

Computeds and Effects skip their callbacks when computed dependencies refresh
to unchanged outcomes. Rebinding to an equal-valued source follows the same
rule. Explicit `Signal.update()` and `Computed.invalidate()` calls force a
change notification from that node.

A distinct but equal dictionary therefore replaces its predecessor and
invalidates dependents. Mutating an existing dictionary through `.value` does
not notify; use replacement or call `Signal.update()` after mutation. Item and
attribute assignment on a `Signal` (`sig[key] = v`, `sig.attr = v`) mutate the
wrapped object in place and notify, because the `Signal` owns that object; a
`Computed` holds a cache and does not forward writes. This is not general
mutation observation. Mutations through aliases remain invisible.

## Recursive resolution and serialization

`deep_unref` explicitly reads reactive values inside supported containers.
Call it inside a computation or effect to subscribe to the reactive values
it reaches. Calling it beforehand does not establish those dependencies.
See [Resolving nested values](resolution.md) for supported types, serialization,
custom handlers, and traversal guarantees.

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

`rx.tap(fn)` creates a lazy cached computation that invokes a callback and
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
callback order or at-most-once execution. Before rerunning an effect, its
computed dependencies are refreshed; if all tracked inputs are unchanged,
the callback is skipped.

Retain each Effect while it should remain active. The queue does not own it.
`dispose()` is idempotent and cancels pending work, including when called from
inside its callback. An effect created in a batch and discarded before exit
may never execute.

Batching provides no rollback or isolated reads. Ordinary code can see
intermediate state, and applied writes are flushed even when the body raises.

### Errors and recovery

A run that raises still subscribes to everything it read before raising, so a
later change to any of those values retries it. Dependencies from an earlier
run that the failed run did not reach are dropped, exactly as after a
successful run.

A `Computed` caches an ordinary exception just as it caches a value. Repeated
reads re-raise that exception without rerunning the callback. A dependency
change or explicit `invalidate()` permits another evaluation. Readers subscribe
even when the read raises, so failure on the first evaluation can recover
automatically. A new failed evaluation counts as a changed outcome; recovery
also counts as changed, even if it returns the last successful value.

Healthy pending effects continue after ordinary callback failures. One failing
callback raises its exception directly; several failures in one flush are
raised as an `ExceptionGroup`. The same rule applies inside and outside
`batch()`. A batch body error alone is re-raised unchanged; simultaneous body
and flush failures are grouped together (using `BaseExceptionGroup` when
necessary).

Control-flow exceptions such as `KeyboardInterrupt` are not cached: they abort
flushing and clear pending work. Active subscriptions remain eligible for future
updates. Feedback that exceeds 100 runs of one effect per flush raises
`RuntimeError` through the same error-reporting mechanism and clears remaining
pending work.

All reactive operations are single-threaded and synchronous. Neither `batch()`
nor `untracked()` may span `await`.
