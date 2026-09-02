# Compute contract

Signified's reactive model has one central rule:

> **Dependencies come from reactive reads, not containment.**

`Signal[T]` stores `T`, `Computed[T]` computes `T`, and `Binding[T]` follows a
`ReactiveValue[T]` while retaining a stable identity. Reactive objects are
valid ordinary Python values, so a signal may store one and a computed function
may return one.

```python
from signified import Binding, Computed, Signal

source = Signal(1)

stored = Signal(source)
calculated = Computed(lambda: source)
following = Binding(source)

assert stored.value is source
assert calculated.value is source
assert following.value == 1
```

## Shallow reads

`unref` crosses exactly one reactive boundary. Likewise, `computed` and
`effect` automatically unwrap direct reactive arguments only. They never walk
an ordinary container looking for reactive descendants.

```python
from signified import Signal, computed, unref

inner = Signal(1)
outer = Signal(inner)
assert unref(outer) is inner

config = {"x": inner}

@computed
def double(config):
    return config["x"].value * 2

result = double(config)
inner.value = 3
assert result.value == 6
```

The `.value` access establishes the dependency. A computation that merely
returns `config` does not depend on the signal contained in it.

## Explicit recursive resolution

Import the `deep` namespace when a whole structure should be resolved and every
reactive leaf should be tracked.

```python
from signified import Signal, deep

values = [Signal(1), {"more": (Signal(2), Signal(3))}]

@deep.computed
def total(values):
    return values[0] + sum(values[1]["more"])

result = total(values)
assert result.value == 6
```

The explicit APIs are `deep.unref`, `deep.computed`, and `deep.effect`.
`deep_unref` remains as a deprecated compatibility alias for `deep.unref`.

## Choosing the right primitive

| Intent | API |
| --- | --- |
| Store a value, including a reactive object or container | `Signal(value)` |
| Derive any Python value | `Computed(function)` |
| Follow or switch between reactive sources | `Binding(source)` |
| Read one reactive boundary | `unref(value)` |
| Resolve all reactive values in a structure | `deep.unref(value)` |
| Resolve direct reactive function arguments | `computed` / `effect` |
| Recursively resolve function arguments | `deep.computed` / `deep.effect` |

## Migrating from implicit deep behavior

This contract is intentionally breaking because affected programs can remain
valid Python while acquiring a different dependency graph. Review these old
patterns explicitly:

- Replace `Signal(other_signal)` with `Binding(other_signal)` when the intent
  was to follow the source. Keep `Signal(other_signal)` when the intent is to
  store the reactive object itself.
- Replace repeated implicit `unref` behavior with `deep.unref`, or read the
  exact `.value` properties the computation needs.
- Replace `computed(fn)(container_of_signals)` with
  `deep.computed(fn)(container_of_signals)` when every contained signal should
  be resolved. Prefer explicit reads when only some leaves are dependencies.
- Make the equivalent change from `effect` to `deep.effect` for side effects
  that need whole-structure resolution.
- Return `source.value` from a `Computed` when it should compute the current
  source value; return `source` when the reactive object itself is the result.

After migration, test both returned values and invalidation behavior: update a
contained reactive leaf and verify that only computations which read that leaf
run again.
