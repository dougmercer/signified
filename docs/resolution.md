# Resolving nested values

Use `deep_unref` to replace reactive values inside nested containers:

```python
from signified import Signal, deep_unref

payload = {"position": [Signal(10), Signal(20)]}
assert deep_unref(payload) == {"position": [10, 20]}
```

Lists, tuples, dictionaries (keys and values), sets, frozensets, and deques
are rebuilt. Object-bearing NumPy arrays preserve their shape and dtype.
Other objects pass through unchanged unless you register their type.

Shared objects stay shared in the result. Cycles and resolved key/member
collisions raise `ValueError`; unhashable keys/members raise `TypeError`.
Errors include the location where resolution failed. Reads inside a computation
or effect create dependencies on the reactive values reached.

## Custom objects

A position can contain reactive coordinates without being iterable. Register a
handler to tell `deep_unref` which fields to visit:

```python
from dataclasses import dataclass

from signified import Signal, deep_unref

@dataclass
class Position:
    x: float | Signal[float]
    y: float | Signal[float]

@deep_unref.register(Position)
def resolve_position(position, resolve):
    return Position(
        x=resolve(position.x, ".x"),
        y=resolve(position.y, ".y"),
    )

position = Position(Signal(10.0), Signal(20.0))
plain = deep_unref({"position": position})
assert plain == {"position": Position(x=10.0, y=20.0)}
assert isinstance(position.x, Signal)  # The input is unchanged.
```

Decide which fields to resolve, what metadata to copy unchanged, and which
object to return. Prefer building a new object instead of mutating the input.
Use the supplied `resolve` on children rather than calling `deep_unref` again:
that keeps cycle detection and shared references working across the traversal.
The optional field label makes errors easier to locate. A handler runs once for
each encountered object, even if it appears more than once in the input.

Registration applies to one exact type. Register subclasses separately when
needed. Refer to the built-in handlers in `src/signified/_resolve.py` for more
examples, including dictionary keys and NumPy arrays.

## Migrating unregistered iterables

Automatic traversal of unregistered iterable types is deprecated and will be
removed in **0.6.0**. It still attempts the old iterable constructor and emits
a `DeprecationWarning`. If reconstruction is unsupported, the original object
is returned; errors while resolving children are not hidden.

Register a handler to keep resolving a custom container. In 0.6.0, unregistered
types will be returned unchanged without inspecting or iterating them.

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
    values = (resolve(value, f"[{i}]") for i, value in enumerate(samples))
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

This helper does not make every Python object JSON-serializable. Dates and
other unsupported objects remain unchanged; format conversion belongs to the
serializer you use afterward.
