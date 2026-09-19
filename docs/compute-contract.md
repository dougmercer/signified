# How updates work

This page describes the rules behind Signified's updates. For an introduction
with everyday examples, start with the [usage guide](usage.md).

## What each object does

| Object | Purpose |
| --- | --- |
| `Signal` | Stores a value you can change. |
| `Computed` | Calculates a value when needed and saves the result or error. |
| `Effect` | Runs an action when the reactive values it reads change. |
| `Binding` | Follows a source you can replace without replacing the binding itself. |

A signal can store another reactive object. A calculation can return one too.
Neither reads that object's value automatically:

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

`unref` reads one reactive object at a time. Operators and decorated functions
follow the same rule. For example, `(outer + 1).value` is itself a `Computed`
because `outer` stores a signal. Use `Binding(inner) + 1` to calculate from the
number instead.

## Which reads trigger updates {#reads-and-equality}

A computation or effect follows the reactive values it reads while running.
These inputs are called its *dependencies*. After each run, only the inputs
read during that run remain dependencies. In a conditional expression, that
means the selected branch is tracked.

`computed` and `effect` read direct reactive arguments once per run. Other
arguments, including lists and dictionaries, pass through unchanged:

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

Reading `x.value` makes `result` follow `x`. Simply returning `config` would not.

Keep computed functions free of actions such as changing application state.
An unread calculation may never run. Its read-only `.value` property also does
not prevent changes to a list or object returned by the function.

## What counts as a change

Signal assignments and calculated results use the same rules:

- Exact built-in `int`, `bool`, `str`, `bytes`, `complex`, `NoneType`, and `float`
  values compare by value. Two float NaNs count as unchanged.
- Different types count as changed, including `1` versus `True`.
- Everything else, including containers, arrays, subclasses of those built-ins,
  and user objects, compares by identity: only the same object is unchanged.
  Signified does not call these objects' equality methods.
- When a value is unchanged, the previously stored object is kept.

A new dictionary therefore counts as a change even if it has the same contents.
Changing an existing dictionary through `.value` does not send an update.
Replace it, call `Signal.update()` after changing it, or assign through the
signal with `state[key] = value`. The [container examples](usage.md#collections-and-item-assignment)
show all three approaches. Attribute assignment through a signal works the same
way; a `Computed` or `Binding` does not forward these writes.

A computation or effect can skip running when its calculated inputs refresh to
unchanged results. Switching a binding to an equal-valued source follows this
rule too. `Signal.update()` and `Computed.invalidate()` explicitly send a change
notification from that object.

## Nested values and serialization {#recursive-resolution-and-serialization}

Call `deep_unref` inside a computation or effect to read reactive values inside
supported containers. Calling it beforehand produces data but does not make
that callback follow the original values. See [Nested values](resolution.md)
for supported types, JSON, custom handlers, and copying limits.

## Read without adding a dependency {#untracked-reads}

Use `untracked()` for incidental reads that should not trigger the surrounding
computation or effect:

```python
from signified import Computed, Effect, Signal, untracked

trigger, other = Signal(0), Signal(1)
derived = Computed(lambda: other.value * 2)
seen = []

def observe():
    current = trigger.value
    with untracked():
        seen.append((current, derived.value))

watcher = Effect(observe)
other.value = 2
assert seen == [(0, 2)]
trigger.value = 1
assert seen[-1] == (1, 4)
watcher.dispose()
```

The effect follows `trigger`, but not `derived` or `other`. The nested
calculation `derived` still tracks its own inputs and returns its current value.
Reads, plugin hooks, errors, and writes work normally. Blocks can nest, and
tracking is restored when a block exits, including after an error.

`rx.tap(fn)` serves a different purpose: it calls `fn` when its calculated value
is evaluated and passes the value through. Cached reads do not repeat the call,
and unread intermediate values are skipped.

## Batching and effect lifetime

`batch()` delays effects until the outermost batch exits. Writes take effect
immediately, and reading a computed value inside the batch returns its current
result. The [usage guide](usage.md#scheduling-and-untracked-reads) has an example.

Outside a batch, effects run before the triggering update returns, after all
calculations affected by that update have been marked for refresh. Multiple
pending notifications can share a run. An effect that writes another value
can cause further runs, so do not rely on effect order or assume each effect
runs only once. Before rerunning an effect, Signified refreshes its calculated
inputs; if all tracked inputs are unchanged, the callback is skipped.

Keep a reference to each effect while it should remain active. Pending work
does not keep it alive. `.dispose()` cancels pending work, can be called from
inside the callback, and is safe to call more than once. An effect created
inside a batch waits for the batch to exit even for its first run; if discarded
before then, it may never run.

Batching does not hide intermediate values or undo changes. If the batch body
raises an error, applied writes remain and pending effects still run.

Run all reactive operations on one thread. `batch()` and `untracked()` are
synchronous blocks and must not contain `await`.

### Errors and recovery

A failed run still follows everything it read before the error. Inputs from
an earlier run that were not read this time are dropped. A later change to
one of the remaining inputs allows the computation or effect to try again.

A `Computed` saves ordinary exceptions just as it saves values. Further reads
raise the saved exception without rerunning the function. An input change or
`.invalidate()` allows another evaluation. A computation or effect that reads
the failed value still tracks that read, allowing recovery after the first
evaluation fails.
Each new failed evaluation counts as a change. Recovery also counts as a
change, even if the result matches the last successful value.

After an ordinary effect error, other pending effects still run. A single
failure is raised directly; multiple failures from processing pending effects
are raised together as an `ExceptionGroup`. These rules apply inside and
outside batches. A batch body error alone is raised unchanged. If both the
body and pending effects fail, the errors are grouped together, using
`BaseExceptionGroup` when necessary.

Control-flow exceptions such as `KeyboardInterrupt` are not saved. They stop
processing pending effects and clear the remaining work. Active effects can
still respond to future changes. If one effect runs more than 100 times while
processing a round of pending effects, Signified reports a `RuntimeError`
through the same error-handling mechanism and clears the remaining work.
