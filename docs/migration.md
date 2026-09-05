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
progress.value = animation
```

A binding has a stable reactive identity while its source changes. Assignment
and `set()` both follow reactive sources and select private plain values:

```python
progress = Binding(0.0)
progress.value = animation
progress.value = 1.0
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
player.progress.value = animation
```

Update annotations according to the role of the value: use `Signal[T]` for
mutable stored state, `Binding[T]` for a stable handle that can change sources,
and `ReactiveValue[T]` when an API only needs to consume any reactive source.
Assigning a reactive object to `Binding.value` follows that source; assigning a
plain object selects a private `Signal` containing it.

`unref` now unwraps one boundary. Use `deep.unref` for recursive resolution:

```python
from signified import deep

resolved = deep.unref(nested)
```

Deep resolution traverses registered container types rather than arbitrary
iterables. Built-in collections are registered by default; use
`@deep.register(MyContainer)` to opt a custom container into traversal.

`computed` and `effect` now unwrap direct reactive arguments only. For
containers of reactive values, either read the required `.value` properties
inside the function or opt into recursive resolution:

```python
total = deep.computed(sum)([a, b])
```

Finally, `Computed(lambda: source)` now returns `source` itself. Use
`Computed(lambda: source.value)` when you want its current value.

See the [compute contract](compute-contract.md) for the complete semantics.
