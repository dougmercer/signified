# Usage Guide

Because this package relies so heavily on overriding "magic methods", the API documentation for this package makes it hard to get an idea of how `signified` works. This page gives a crash course through several usage examples.

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
is_logged_in = username.is_not(None)

@computed
def welcome(name):
    return f"Welcome back, {name}!"

message = is_logged_in.where(welcome(username), "Please log in")

print(message)  # <"Please log in">
username.value = "admin"
print(message)  # <"Welcome back, admin!">
```

## `reactive_method`

Use `@reactive_method(...)` for instance methods that depend on reactive attributes.

```python
from dataclasses import dataclass
from typing import List

from signified import Signal, reactive_method

@dataclass
class Item:
    name: str
    price: float

class Cart:
    def __init__(self, items: List[Item]):
        self.items = Signal(items)
        self.tax_rate = Signal(0.125)

    @reactive_method("items", "tax_rate")
    def total(self):
        subtotal = sum(item.price for item in self.items.value)
        return subtotal * (1 + self.tax_rate.value)

cart = Cart([Item("Book", 20), Item("Pen", 4)])
total_price = cart.total()

print(total_price)  # <27.0>
cart.tax_rate.value = 0.25
print(total_price)  # <30.0>
cart.items[0] = Item("Rare book?", 400)
print(total_price)  # <505.0>
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
