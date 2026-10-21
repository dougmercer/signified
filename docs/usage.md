# Usage guide

Start with a `Signal` for each value your application changes. Build calculations
from those signals, then use effects for actions such as logging or updating a display.

## Signals and calculated values {#signals-computed-values-and-bindings}

Read a signal with `.value` and assign to `.value` to change it. Python operators
create a `Computed` that follows its inputs:

```python
from signified import Signal

price = Signal(10)
quantity = Signal(2)
total = price * quantity

print(total.value)  # 20   (an ordinary Python value)
quantity.value = 3
print(total.value)  # 30
```

A computed value is calculated when read and saved until an input changes.
Its `.value` is read-only. You can use it in further calculations, such as
`with_tax = total * 1.2`.

### Use your own functions {#computed-from-functions-computed}

`@computed` makes a function return a `Computed`. Direct signal arguments are
read for you, so the function receives their values:

```python
from signified import Signal, computed

@computed
def average(values):
    return sum(values) / len(values)

numbers = Signal([2, 4, 6])
result = average(numbers)
print(result.value)  # 4.0
numbers.value = [10, 20]
print(result.value)  # 15.0
```

For an existing function, use `computed(sum)(numbers)` or
`numbers.rx.map(sum)`. Keep these functions focused on calculating a result;
use an effect for work that should happen automatically.

## Run actions when values change

`@effect` runs a function immediately and again when the values it reads change.
Keep the returned object while the effect should stay active, then call
`.dispose()` to stop it:

```python
from signified import Signal, effect

@effect
def show_total(total):
    print("Total:", total)

price = Signal(10)
quantity = Signal(2)
watcher = show_total(price * quantity)  # Total: 20
quantity.value = 3                     # Total: 30
watcher.dispose()
quantity.value = 4                     # No output
```

An effect that reads only a calculation skips running when that calculation
recalculates to the same result. The
[effect examples](examples.md#effects)
show effects that refresh a display, autosave settings, and rebuild an index
when files change.

### Group related changes {#scheduling-and-untracked-reads}

Use `batch()` to delay effects until a group of writes is finished:

```python
from signified import Effect, Signal, batch

price, quantity = Signal(10), Signal(2)
watcher = Effect(lambda: print(price.value * quantity.value))  # 20
with batch():
    price.value = 12
    quantity.value = 3
# Prints 36 once the block exits.
watcher.dispose()
```

Values change immediately inside the block; batching does not undo writes if
an error occurs. Use a graph from one thread at a time, and do not put `await`
inside `batch()` or `untracked()`.

Use `untracked()` when a read inside an effect or calculation should not make
it run again when that value changes. See [How updates work](compute-contract.md)
for an example, effect timing, and error handling.

## Ask which values changed {#watchers}

An effect runs as soon as a value changes. Code that works in steps of its own,
such as a renderer drawing frames or a game loop, often wants the opposite: to
ask, once per step, which of many values changed, and redo the work for those
only. A `Watcher` answers that without reading every value:

```python
from signified import Signal, Watcher, computed

frame = Signal(0)
speeds = {"still": 0.0, "moving": 2.0}
positions = {name: computed(lambda f, speed=speed: speed * f)(frame) for name, speed in speeds.items()}

watcher = Watcher()
for name, position in positions.items():
    watcher.watch(position, name)

frame.value = 1
print(watcher.changed())  # ['moving']: "still" recalculated to the same 0.0
print(watcher.changed())  # []
```

- A change only marks the watch; no code runs. `changed()` then brings the
  marked calculations up to date and reports those whose result changed, each
  key once, in the order they changed. Calculations nothing changed are not
  read.
- Several values can share a key; it is reported once when any of them changes.
- A value that changes and changes back between two calls is still reported.
- A calculation that raises is reported; reading it raises the error.
- `unwatch(key)` stops the watches reported as that key. Watched values and
  keys are held until then, or until the watcher is collected.

## Lists and dictionaries {#collections-and-item-assignment}

Reading an item through a signal creates a calculation. Assigning an item
through the signal also tells dependent calculations to update:

```python
from signified import Signal, computed

numbers = Signal([1, 2, 3])
first = numbers[0]
total = computed(sum)(numbers)

numbers[0] = 9
print(first.value)  # 9
print(total.value)  # 14

numbers.value.append(4)  # Changing the raw list does not send an update.
print(total.value)       # 14 (the saved result)
numbers.update()         # Tell Signified about the change.
print(total.value)       # 18

numbers.value = [5, 6]   # Replacing the list also sends an update.
print(total.value)       # 11
```

Dictionaries work the same way: `settings["theme"] = "light"` sends an update;
`settings.value["theme"] = "light"` needs a subsequent `settings.update()`.
Changes made through another reference to the raw object also need notification.

### Signals inside containers {#shallow-and-deep-argument-resolution}

A list or dictionary can contain signals. Merely storing them does not make
calculations follow their values. Read the signals inside your function, or
use `deep_unref` to read all of them:

```python
from signified import Computed, Signal, deep_unref

values = [Signal(1), Signal(2)]
total = Computed(lambda: sum(deep_unref(values)))
print(total.value)  # 3
values[0].value = 10
print(total.value)  # 12
```

Keep `deep_unref` **inside** the function so its reads are tracked. The
[nested values guide](resolution.md) covers supported containers, JSON, and
custom objects.

### Skip updates for equal contents {#custom-equality}

A new list counts as a change even if its contents match the old one, because
Signified compares lists, dictionaries, arrays, and your own objects by
identity. Pass `equal=` to compare them your way:

```python
from signified import Signal, effect

@effect
def show(point):
    print("Point:", point)

point = Signal([0, 0], equal=lambda old, new: old == new)
watcher = show(point)  # Point: [0, 0]
point.value = [0, 0]   # Same contents: no update
point.value = [1, 0]   # Point: [1, 0]
watcher.dispose()
```

When `equal(old, new)` returns `True`, the signal keeps the old object and
nothing that depends on it updates. `Computed` accepts `equal=` too. For a value
built with operators or `@computed`, set it afterwards with `.rx.with_equal()`,
for example `transform = (rotation @ scale).rx.with_equal(np.array_equal)`.

## Attributes and methods {#attribute-access-method-calls-and-assignment}

You can read attributes and call methods through a signal:

```python
from types import SimpleNamespace
from signified import Signal

person = Signal(SimpleNamespace(name="Alice"))
name = person.name
person.name = "Bob"
print(name.value)  # Bob

text = Signal("  Hello, World!  ")
message = text.strip().lower()
print(message.value)  # hello, world!
```

Only `Signal` forwards attribute and item writes to the object it holds.
An attribute must already exist on that object. Method calls produce calculated
values; calling a method that changes the raw object does not automatically
send an update. For example, use `numbers.value.append(4)` followed by
`numbers.update()` to change a list.

## Choose between values {#conditional-logic-with-where}

Use `.rx` for operations that need a reactive alternative to Python syntax:

```python
from signified import Signal

username = Signal(None)
message = username.rx.is_not(None).rx.where("Signed in", "Please log in")
print(message.value)  # Please log in
username.value = "admin"
print(message.value)  # Signed in
```

For a reactive equality check, use `x.rx.eq(y)`. For reactive truthiness, use
`x.rx.as_bool()`. The [operator cheatsheet](magic-methods.md) lists the other
operations and their Python counterparts.

## Switch inputs with Binding {#replacing-a-reactive-source-with-binding}

A `Signal` holds a value. A `Binding` can hold a value *or* follow another
reactive value, and you can change which at any time. Calculations built from
the binding keep working through every switch.

This suits an object's properties. A shape's `x` position might be a fixed
number at first, then follow an animation later:

```python
from signified import Binding, Signal

frame = Signal(0)
x = Binding(0)        # a plain number for now
label_x = x + 10      # e.g. a label that sits to the right of the shape

x.value = 5           # set a number, like a Signal
print(label_x.value)  # 15

x.value = frame * 2   # now follow an animation
frame.value = 30
print(label_x.value)  # 70
```

### Why not a Signal?

With `x = Signal(0)`, there is no good way to make `x` follow `frame * 2`:

- `x.value = frame * 2` stores the `Computed` object itself. `label_x.value`
  becomes a `Computed`, not a number.
- `x.value = (frame * 2).value` copies the current number once. `x` does not
  change again when `frame` does.
- Rebuilding `label_x` from `frame * 2` works, but anything still holding the
  old `label_x`, such as an effect or another object, is left behind.

A `Binding` gives the object one handle for its whole life, while you choose
what drives it.

### Build on the current source

`x.source` returns whatever `x` currently follows. A binding can also follow
another binding. To layer a new calculation on top of the current source, use
`.derive()`:

```python
x.derive(lambda previous: previous + 100)  # shift whatever x was following
print(label_x.value)  # 170
```

Use `previous` inside that function. Referring to `x` would make the binding
depend on itself. Direct self-binding is rejected; indirect loops raise when read.

## Track attribute reassignment {#tracked-fields}

A calculation that reads `unref(material.roughness)` follows a signal stored in
that attribute, but it cannot see the attribute itself being replaced.
`tracked_fields` makes reassignment visible:

```python
from dataclasses import dataclass
from signified import Computed, HasValue, Signal, tracked_fields, unref

@tracked_fields
@dataclass(slots=True)
class Material:
    roughness: HasValue[float] = 0.5

material = Material()
doubled = Computed(lambda: unref(material.roughness) * 2)
material.roughness = 0.25
print(doubled.value)  # 0.5
material.roughness = Signal(0.1)
print(doubled.value)  # 0.2
```

Reading the attribute returns exactly what was stored; it never unwraps.
Assigning a signal replaces the stored one instead of writing into it. Pass
names, as in `@tracked_fields("roughness")`, to track only some attributes, or
to track attributes of a class that is not a dataclass. The
[dashboard example](examples.md#dashboard)
drives an effect from a tracked dataclass, with batching.

## Force a calculation to refresh {#manual-invalidation}

If a calculation reads through an ordinary Python object, Signified cannot see
that object's attributes being replaced. For classes you control, use
[`tracked_fields`](#tracked-fields). Otherwise, call `.invalidate()` to
recalculate on the next read:

```python
from types import SimpleNamespace
from signified import Computed, Signal

holder = SimpleNamespace(source=Signal(5))
doubled = Computed(lambda: holder.source.value * 2)
print(doubled.value)  # 10
holder.source = Signal(20)
print(doubled.value)  # 10
doubled.invalidate()
print(doubled.value)  # 40
```

## More helpers {#utility-helpers}

See the [API reference](api.md) for:

- `unref(value)`: accept either a plain value or a signal, computed value, or binding.
- `as_rx(value)`: wrap a plain value in a signal; leave reactive values unchanged.
- `has_value` and `is_reactive`: check and narrow types.
- `Signal.at(value)`: temporarily change a value inside a `with` block.
- `x.rx.tap(fn)`: call `fn` with each newly calculated value (runs only when something reads the result).

For editor and type-checking support, see [Type checkers](type-checkers.md).
