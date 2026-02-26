---
hide:
  - navigation
---

# Usage Guide

This guide walks through common usage patterns with examples. For a complete reference, see the [API docs](api.md).

## Signals and Computed Values

`Signal` holds mutable state.

`Computed` represents derived state. It subscribes to dependencies and updates when they change.

### Reading the underlying value (`.value`)

`Signal` and `Computed` display as `<...>` to indicate they are reactive objects.
Use `.value` when you need the plain Python value.

```python
from signified import Signal

price = Signal(19.99)
quantity = Signal(2)
subtotal = price * quantity

print(subtotal)        # <39.98> (reactive)
print(subtotal.value)  # 39.98   (plain float)

quantity.value = 3
print(subtotal.value)  # 59.97
```

`Signal.value` is read/write. `Computed.value` is read-only and updates from dependencies.

### Computed from operators

```python
from signified import Signal

price = Signal(19.99)
quantity = Signal(2)
subtotal = price * quantity

print(subtotal)  # <39.98>
quantity.value = 3
print(subtotal)  # <59.97>
```

### Computed from functions (`@computed`)

```python
from signified import Signal, computed

numbers = Signal([1, 2, 3, 4, 5])

@computed
def stats(nums):
    return {
        "sum": sum(nums),
        "mean": sum(nums) / len(nums),
        "min": min(nums),
        "max": max(nums),
    }

result = stats(numbers)
print(result)  # <{'sum': 15, 'mean': 3.0, 'min': 1, 'max': 5}>

numbers.value = [2, 4, 6, 8, 10]
print(result)  # <{'sum': 30, 'mean': 6.0, 'min': 2, 'max': 10}>
```

### Composing Computed values

`Computed` values can be used as dependencies for other computed values.

```python
from signified import Signal, computed

x = Signal(3)
x_squared = x**2

@computed
def plus_one(v):
    return v + 1

y = plus_one(x_squared)
print(y)  # <10>

x.value = 5
print(y)  # <26>
```

This composition is the core pattern: define state once, derive the rest.

## Attribute Access, Method Calls, and Assignment

You can reactively read attributes and call methods from objects inside signals.

```python
from dataclasses import dataclass
from signified import Signal

@dataclass
class Person:
    name: str
    age: int

    def greet(self):
        return f"Hello, I'm {self.name} and I'm {self.age} years old!"

person = Signal(Person("Alice", 30))

name_display = person.name
greeting = person.greet()

print(name_display)  # <"Alice">
print(greeting)      # <"Hello, I'm Alice and I'm 30 years old!">

# __setattr__ support updates the wrapped object and notifies dependents
person.name = "Bob"
print(name_display)  # <"Bob">
print(greeting)      # <"Hello, I'm Bob and I'm 30 years old!">
```

Method chaining works too:

```python
from signified import Signal

text = Signal("  Hello, World!  ")
processed = text.strip().lower().replace(",", "")

print(processed)  # <"hello world!">
text.value = "  Goodbye, World!  "
print(processed)  # <"goodbye world!">
```

## Collections and Item Assignment

Indexing is reactive, and `__setitem__` can notify dependents for `list` and `dict`.

```python
from signified import Signal, computed

numbers = Signal([1, 2, 3])
total = computed(sum)(numbers)

print(numbers[0])  # <1>
print(total)       # <6>

numbers[0] = 9
print(total)       # <14>
```

```python
from signified import Signal

config = Signal({"theme": "dark", "font_size": 14})
theme = config["theme"]

print(theme)  # <"dark">
config["theme"] = "light"
print(theme)  # <"light">
```

## Conditional Logic with `where`

`where(a, b)` picks `a` when the condition is truthy, otherwise `b`.

```python
from signified import Signal, computed

username = Signal(None)
is_logged_in = username.rx.is_not(None)

@computed
def welcome(name):
    return f"Welcome back, {name}!"

message = is_logged_in.rx.where(welcome(username), "Please log in")

print(message)  # <"Please log in">
username.value = "admin"
print(message)  # <"Welcome back, admin!">
```


## Applying functions

### `map`

`map` applies a function to a reactive value and returns a new `Computed`. It's a shorthand for `computed(fn)(source)` — the result re-evaluates whenever the source changes.

```python
from signified import Signal

temperature_c = Signal(20)


temperature_f = temperature_c.rx.map(lambda c: (c * 9 / 5) + 32)
# equivalent to:
# temperature_f = computed(lambda c: (c * 9 / 5) + 32)(temperature_c)

print(temperature_f.value)  # 68.0
temperature_c.value = 25
print(temperature_f.value)  # 77.0
```

### `peek` vs `effect`

Use `peek` when you want a side-effect to fire only when you explicitly read `.value` — useful for debugging or logging on demand. Use `effect` when you want a side-effect to fire automatically on every change.

`peek` is lazy like other `Computed` values: it only runs when `.value` is read.

`effect` is eager: it runs immediately and again on every source update.

=== "peek"

    ```python
    from signified import Signal

    price = Signal(10)
    total = price.rx.map(lambda p: p * 1.2).rx.peek(lambda v: print("total:", v))

    price.value = 10  # Nothing happens
    price.value = 20  # Nothing happens
    price.value = 30  # Nothing happens
    price.value = 10  # Nothing happens
    total.value  # prints: 'total: 12.0'
    price.value = 20  # Nothing happens
    total.value  # prints: 'total: 24.0'
    ```

=== "effect"

    ```python
    from signified import Signal

    price = Signal(10)
    total_effect = price.rx.map(lambda p: p * 1.2).rx.effect(lambda v: print("total:", v))  # prints: 'total: 12.0'
    price.value = 20  # prints: 'total: 24.0'

    total_effect.dispose()
    price.value = 30  # Nothing happens
    ```

## Utility Helpers

`unref` makes functions work with either plain values or reactive values.

```python
from signified import HasValue, Signal, unref

def process_data(value: HasValue[float]) -> float:
    return unref(value) * 2

print(process_data(4))          # 8
print(process_data(Signal(5)))  # 10
```

Related helpers:

- `deep_unref`: recursively unwraps nested containers of reactive values
- `as_signal`: wraps plain values into `Signal` (or returns the input signal)
- `has_value`: type guard for checking `HasValue[T]`
- `Signal.at(...)`: temporary scoped value override via context manager

## Manual Invalidation

Most updates flow automatically through the reactive graph. Occasionally you may rewire dependencies through a non-reactive container (e.g. replacing an attribute on a plain Python object). In that case, call `invalidate()` to force a `Computed` to fully re-evaluate on next read.

```python
from signified import Signal, computed


class Holder:
    def __init__(self, sig):
        self.sig = sig


holder = Holder(Signal(5))
derived = computed(lambda holder: holder.sig * 2)(holder)

print(derived.value)  # 10

holder.sig = Signal(20)  # non-reactive rewire — graph doesn't know
print(derived.value)     # still 10

derived.invalidate()
print(derived.value)     # 40
```
