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

If a calculation produces the same result, an effect watching only that result
can skip running. Use [`rx.tap`](api.md#signified._mixin._ReactiveNamespace.tap)
for debugging a calculation when it is read; it does not run automatically
for every change.

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
an error occurs. Run reactive operations on one thread, and do not put `await`
inside `batch()` or `untracked()`.

Use `untracked()` when a read inside an effect or calculation should not make
it run again when that value changes. See [How updates work](compute-contract.md)
for an example, effect timing, and error handling.

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

Use `Binding` when existing calculations should switch to a different source:

```python
from signified import Binding, Signal

left, right = Signal(1), Signal(10)
selected = Binding(left)
doubled = selected * 2
print(doubled.value)  # 2
selected.value = right
print(doubled.value)  # 20
right.value = 12
print(doubled.value)  # 24
selected.value = 5    # Use a plain value as the new source.
print(doubled.value)  # 10
```

`selected.source` returns the current source. A binding can also follow another
binding. To build a new calculation from the previous source, use `.derive()`:

```python
from signified import Binding, Signal

value = Binding(Signal(2))
value.derive(lambda previous: previous * 3)
print(value.value)  # 6
```

Use `previous` inside that function. Referring to `value` would make the binding
depend on itself. Direct self-binding is rejected; indirect loops raise when read.

`Signal(other_signal)` stores the signal object itself. Use `Binding(other_signal)`
when you want to follow its current value.

## Force a calculation to refresh {#manual-invalidation}

If you replace an input through an ordinary Python object, Signified may not
see the change. Call `.invalidate()` to recalculate on the next read:

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

For editor and type-checking support, see [Type checkers](type-checkers.md).
