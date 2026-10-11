# How updates work

This page describes the rules behind Signified's updates. For an introduction
with everyday examples, start with the [usage guide](usage.md).

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
To compare by contents, pass an `equal(old, new)` function as `equal=` to
`Signal` or `Computed`, or call `x.rx.with_equal(equal)` on a value built by an
operator or `@computed`. It is called only when the rules above report a
change, so it can make more values count as unchanged, never fewer. See
[Skip updates for equal contents](usage.md#custom-equality).

Changing an existing dictionary through `.value` does not send an update.
Replace it, call `Signal.update()` after changing it, or assign through the
signal with `state[key] = value`. The [container examples](usage.md#collections-and-item-assignment)
show all three approaches. Attribute assignment through a signal works the same
way; a `Computed` or `Binding` does not forward these writes.

A computation or effect can skip running when its calculated inputs refresh to
unchanged results. Switching a binding to an equal-valued source follows this
rule too. `Signal.update()` and `Computed.invalidate()` explicitly send a change
notification from that object.

## Nested values {#recursive-resolution-and-serialization}

A signal can hold another reactive value, and a calculation can return one.
Neither reads it for you:

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

`unref`, `Binding`, operators, and decorated functions all read one level at a
time. For example, `(outer + 1).value` is a `Computed`, because `outer` holds a
signal. Use `Binding(inner) + 1` to calculate from the number instead.

To read reactive values inside lists, dictionaries, and other containers, call
`deep_unref` inside the computation or effect. Calling it beforehand gives you
the data, but the callback will not follow the original values. See
[Nested values](resolution.md) for supported types, JSON, and custom handlers.

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
Blocks can nest, and tracking resumes when a block exits, even after an error.

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

Each thread tracks reads, batches, and runs effects on its own. Separate graphs
can run on separate threads at the same time, and a graph built on one thread
can be used on another afterwards. Use one graph from one thread at a time:
reading a `Computed` while another thread is computing it raises
`RuntimeError`. `batch()` and `untracked()` apply to the thread that enters
them; they are synchronous blocks and must not contain `await`.

### Errors and recovery

A `Computed` saves an ordinary exception the same way it saves a value:

```python
from signified import Computed, Signal

divisor = Signal(0)
ratio = Computed(lambda: 10 / divisor.value)
try:
    ratio.value
except ZeroDivisionError:
    print("failed")  # failed
divisor.value = 2
print(ratio.value)  # 5.0
```

Reading `ratio` again raises the saved error without rerunning the function,
until an input changes or you call `.invalidate()`. A failed run still follows
the inputs it read before the error, which is how changing `divisor` lets
`ratio` recover. For anything that reads `ratio`, each new failure counts as a
change, and so does recovering, even to the last successful value.

When an effect raises, the other pending effects still run. A single failure
is raised as-is; several are raised together as an `ExceptionGroup`. This also
applies inside a batch. If the batch body raises as well, its error is grouped
with the effect errors, in a `BaseExceptionGroup` when needed.

Exceptions that are not `Exception` subclasses, such as `KeyboardInterrupt`,
are never saved. They stop and discard the pending effects, which still respond
to later changes. If one effect runs more than 100 times in a single round of
updates, usually because effects keep changing each other's inputs, Signified
raises `RuntimeError` and discards the remaining work.
