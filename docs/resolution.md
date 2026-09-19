# Resolving nested values

Use `deep_unref` to replace reactive values inside nested containers:

```python
from signified import Signal, deep_unref

payload = {"position": [Signal(10), Signal(20)]}
assert deep_unref(payload) == {"position": [10, 20]}
```

Exact lists, tuples, dictionaries (keys and values), sets, frozensets, and
deques are rebuilt. With NumPy installed, exact arrays containing Python
objects are rebuilt with their shape and dtype preserved; numeric arrays pass
through unchanged. Unknown types and subclasses pass through by identity
without inspection or iteration unless you register their exact type.

Each occurrence is resolved independently. Repeated references to a container
produce separate rebuilt containers; shared identity is not preserved. Cyclic
inputs eventually raise Python's `RecursionError`.

Resolved key/member collisions raise `ValueError`; unhashable keys/members raise
`TypeError`. Reads inside a computation or effect create dependencies on the
reactive values reached. Handler exceptions propagate unchanged.

Unknown objects may hide unresolved reactive values. Results are not necessarily
detached from their inputs, and traversal is not a globally atomic snapshot.

## Serialization

Resolve reactive values before handing ordinary data to a serializer:

```python
import json
from signified import Effect, Signal, deep_unref

x, y = Signal(1), Signal(2)
payload = {"position": [x, y]}
encoded = json.dumps(deep_unref(payload))
assert json.loads(encoded) == {"position": [1, 2]}

# Resolve inside the callback to subscribe to the reached leaves.
sent = []
watcher = Effect(lambda: sent.append(json.dumps(deep_unref(payload))))
x.value = 3
assert json.loads(sent[-1]) == {"position": [3, 2]}
watcher.dispose()
```

For application objects, explicitly project the fields you want to serialize.
The serializer remains responsible for dates, domain objects, and format rules;
`deep_unref` does not guarantee that its result is serializable.

## Custom objects

A position can contain reactive coordinates without being iterable. Register a
handler to tell `deep_unref` which fields to visit:

```python
from dataclasses import dataclass

from signified import ResolveContext, Signal, deep_unref

@dataclass
class Position:
    x: float | Signal[float]
    y: float | Signal[float]

@deep_unref.register(Position)
def resolve_position(position: Position, resolve: ResolveContext) -> Position:
    return Position(
        x=resolve(position.x),
        y=resolve(position.y),
    )

position = Position(Signal(10.0), Signal(20.0))
plain = deep_unref({"position": position})
assert plain == {"position": Position(x=10.0, y=20.0)}
assert isinstance(position.x, Signal)  # The input is unchanged.
```

Decide which fields to resolve, what metadata to copy unchanged, and which
object to return. Prefer building a new object instead of mutating the input.
Use the supplied `resolve` on children rather than calling `deep_unref` again:
that uses the same registered handlers throughout the traversal. A handler runs
for each occurrence of an object, including repeated references.

Registration applies to one exact type. Register subclasses separately when
needed. Registrations replace any previous handler for that exact type. A
handler defines which children are reached; call `resolve` on each intended
child. Return types can change, so general `deep_unref` results are typed as
`Any`. Refer to the built-in handlers in `src/signified/_resolve.py` for more
examples, including dictionary keys and NumPy arrays.

## Migrating unregistered iterables

Automatic traversal of unregistered iterable types was deprecated in 0.5.1
and is removed in **0.6.0**. Errors raised by registered handlers propagate
to the caller.

Register a handler to keep resolving a custom container. Unregistered
types are returned unchanged without inspecting or iterating them.

For example, this custom iterable holds reactive readings and a label. Its
handler resolves every reading and carries the label into the new container:

```python
from signified import Signal, deep_unref

class Samples:
    def __init__(self, values, label=""):
        self.values = list(values)
        self.label = label

    def __iter__(self):
        return iter(self.values)

@deep_unref.register(Samples)
def resolve_samples(samples, resolve):
    values = (resolve(value) for value in samples)
    return Samples(values, label=samples.label)

samples = Samples([Signal(10), Signal(20)], label="sensor A")
plain = deep_unref({"readings": samples})
assert list(plain["readings"]) == [10, 20]
assert plain["readings"].label == "sensor A"
assert all(isinstance(value, Signal) for value in samples)
```

The old iterable fallback could reconstruct the readings but lose the label,
because it only passed items to the constructor. Registration explicitly
preserves both. It also avoids the pre-0.6 deprecation warning and keeps the
container's contents resolving in 0.6.0.
