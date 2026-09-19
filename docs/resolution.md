# Resolving nested values

Use `deep_unref` to replace signals, computed values, and bindings inside
containers with their current values:

```python
from signified import Signal, deep_unref

payload = {"position": [Signal(10), Signal(20)]}
assert deep_unref(payload) == {"position": [10, 20]}
```

## Save or send data as JSON {#serialization}

Read nested values before passing data to a serializer. Keep that read inside
an effect if the output should follow changes:

```python
import json
from signified import Effect, Signal, deep_unref

x, y = Signal(1), Signal(2)
payload = {"position": [x, y]}
sent = []
watcher = Effect(lambda: sent.append(json.dumps(deep_unref(payload))))
assert json.loads(sent[-1]) == {"position": [1, 2]}
x.value = 3
assert json.loads(sent[-1]) == {"position": [3, 2]}
watcher.dispose()
```

For a one-time result, use `json.dumps(deep_unref(payload))` directly.
`deep_unref` only reads reactive values; dates and custom objects still need
conversion to a format your serializer accepts.

## Custom objects

Register a function to tell `deep_unref` how to rebuild your own type. Use the
supplied `resolve` function on each field you want to read:

```python
from dataclasses import dataclass
from signified import ResolveContext, Signal, deep_unref

@dataclass
class Position:
    x: float | Signal[float]
    y: float | Signal[float]

@deep_unref.register(Position)
def resolve_position(position: Position, resolve: ResolveContext) -> Position:
    return Position(x=resolve(position.x), y=resolve(position.y))

position = Position(Signal(10.0), Signal(20.0))
plain = deep_unref({"position": position})
assert plain == {"position": Position(x=10.0, y=20.0)}
assert isinstance(position.x, Signal)  # The input is unchanged.
```

Choose which fields to resolve and which to copy unchanged. Prefer returning
a new object rather than changing the input. Use the supplied `resolve` instead
of calling `deep_unref` again so the same registered handlers are used throughout.

Registration applies to the exact type; register subclasses separately.
Registering another handler for that type replaces the previous one. Handlers
can return a different type, so `deep_unref` results are typed as `Any`.
See the [API reference](api.md#signified.deep_unref) for signatures.

## Supported values

- Built-in lists, tuples, dictionaries (keys and values), sets, frozensets, and
  `collections.deque` objects are rebuilt. Subclasses need their own handlers.
- With NumPy installed, arrays containing Python objects are rebuilt with their
  shape and dtype preserved. Numeric arrays pass through unchanged. Array
  subclasses need their own handlers.
- Unknown objects pass through unchanged, without being inspected or iterated.
  They may still contain reactive values or share mutable data with the input.
- Each occurrence is resolved independently, including calls to custom handlers.
  Two references to one container become separate rebuilt containers.
- Cycles eventually raise `RecursionError`. Duplicate keys or set members after
  resolution raise `ValueError`; unhashable keys or members raise `TypeError`.
  Errors from handlers pass through unchanged.

The result is not necessarily an independent copy, serializable data, or a
snapshot taken at a single instant. Reads inside a computation or effect track
only the reactive values reached during traversal.

## Upgrading custom containers {#migrating-unregistered-iterables}

In 0.6, unregistered iterable types pass through unchanged. Add a handler like
the one above if you relied on automatic traversal. See
[Migrating to 0.6](migration.md#container-arguments-and-serialization).
