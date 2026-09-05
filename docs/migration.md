# Migrating to 0.6

Version 0.6 makes reactive reads explicit: **dependencies come from reads, not
containment.**

Use `Binding` when you meant to follow another reactive source:

```python
# Before
value = Signal(source)

# After
value = Binding(source)
```

The same change applies when a signal starts with a plain value but is assigned
a reactive source later. In earlier versions, assigning the source to
`Signal.value` implicitly followed it:

```python
# Before
progress = Signal(0.0)
progress.value = animation  # animation is a reactive value

# After
progress = Binding(0.0)
progress.bind(animation)
```

A binding has a stable reactive identity while its source changes. Use
`bind()` to follow a reactive source and `set()` to select a plain value:

```python
progress = Binding(0.0)
progress.bind(animation)
progress.set(1.0)
```

This pattern is useful for public properties that downstream computations have
already captured. Replacing the property itself would leave those computations
subscribed to the previous object:

```python
class Player:
    def __init__(self) -> None:
        self.progress = Binding(0.0)

player = Player()
doubled = computed(lambda value: value * 2)(player.progress)
player.progress.bind(animation)
```

Update annotations according to the role of the value: use `Signal[T]` for
mutable stored state, `Binding[T]` for a stable handle that can change sources,
and `ReactiveValue[T]` when an API only needs to consume any reactive source.
`Binding.value` is read-only; assigning to it raises an error so that selecting
a plain value and following a reactive source remain explicit operations.

`unref` now unwraps one boundary. Use `deep.unref` for recursive resolution:

```python
from signified import deep

resolved = deep.unref(nested)
```

`computed` and `effect` now unwrap direct reactive arguments only. For
containers of reactive values, either read the required `.value` properties
inside the function or opt into recursive resolution:

```python
total = deep.computed(sum)([a, b])
```

Finally, `Computed(lambda: source)` now returns `source` itself. Use
`Computed(lambda: source.value)` when you want its current value.

See the [compute contract](compute-contract.md) for the complete semantics.
