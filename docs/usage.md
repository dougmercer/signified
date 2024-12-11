# Usage Guide

Signified is a reactive programming library that helps you create and manage values that automatically update when their dependencies change. This guide will walk you through common usage patterns and features.

## Basic Concepts

### Signals

A `Signal` is a container for a mutable reactive value. When you change a signal's value, any computations that depend on it will automatically update.

```python
from signified import Signal

name = Signal("Alice")
greeting = "Hello, " + name

print(greeting)  # "Hello, Alice"
name.value = "Bob"
print(greeting)  # "Hello, Bob"
```

### Computed Values

Computed values are derived from other reactive values. They can be constructed implicitly using overloaded Python operators or explicitly using the `computed` decorator.

```python
from signified import Signal

a = Signal(3)
b = Signal(4)

# c is a Computed object that will automatically update when a or b are updated
c = (a ** 2 + b ** 2) ** 0.5

print(c)  # 5

a.value = 5
b.value = 12

print(c)  # 13
```

```python
from signified import Signal, computed

numbers = Signal([1, 2, 3, 4, 5])

@computed
def stats(nums):
    return {
        'sum': sum(nums),
        'mean': sum(nums) / len(nums),
        'min': min(nums),
        'max': max(nums)
    }

result = stats(numbers)
print(result)  # {'sum': 15, 'mean': 3.0, 'min': 1, 'max': 5}

numbers.value = [2, 4, 6, 8, 10]
print(result)  # {'sum': 30, 'mean': 6.0, 'min': 2, 'max': 10}
```

## Working with Data

### Collections (Lists, Dicts, etc.)

Signified handles collections like lists and dictionaries **somewhat well**, but there are currently [some rough edges](limitations.md).

```python
from signified import Signal, computed

# Working with lists
numbers = Signal([1, 2, 3, 4, 5])
doubled = computed(lambda x: [n * 2 for n in x])(numbers)

print(doubled)  # [2, 4, 6, 8, 10]
numbers.value = [5, 6, 7]
print(doubled)  # [10, 12, 14]

# Modifying lists
numbers[0] = 10  # Notifies observers
print(numbers)  # [10, 6, 7]
```

```python
from signified import Signal, computed

# Working with dictionaries
config = Signal({"theme": "dark", "fontSize": 14})
theme = config["theme"]
font_size = config["fontSize"]

print(theme)      # "dark"
print(font_size)  # 14

config.value = {"theme": "light", "fontSize": 16}
print(theme)      # "light"
print(font_size)  # 16
```

### NumPy

Signified integrates well with NumPy arrays:

```python
from signified import Signal
import numpy as np

matrix = Signal(np.array([[1, 2], [3, 4]]))
vector = Signal(np.array([1, 1]))

result = matrix @ vector  # Matrix multiplication

print(result)  # array([3, 7])

matrix.value = np.array([[2, 2], [4, 4]])
print(result)  # array([4, 8])
```

## Other Topics

### Conditional Logic

Use the `where()` method for conditional computations:

```python
from signified import Signal

username = Signal(None)
is_logged_in = username.is_not(None)

message = is_logged_in.where(f"Welcome back, {username}!", "Please log in")

print(message)  # "Please log in"
username.value = "admin"
print(message)  # "Welcome back, admin!"
```

### Reactive Attribute Access and Method Calls

Signified supports reactively accessing attributes, properties, or methods on the underlying value.

Here, we construct a simple class and show that we can create `Computed` objects that reactively track the value of attributes stored within he underlying object.

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

# Access attributes reactively
name_display = person.name
age_display = person.age
greeting = person.greet()

print(name_display)  # "Alice"
print(age_display)  # 30
print(greeting)     # "Hello, I'm Alice and I'm 30 years old!"

# Update through the signal
person.name = "Bob"
person.age = 35

print(name_display)  # "Bob"
print(age_display)  # 35
print(greeting)     # "Hello, I'm Bob and I'm 35 years old!"
```

Therefore, if the underlying object supports method chaining, we can easily create reactive values that apply several methods in sequence.

```python
from signified import Signal

text = Signal("  Hello, World!  ")
processed = text.strip().lower().replace(",", "")

print(processed.value)  # "hello world!"
text.value = "  Goodbye, World!  "
print(processed.value)  # "goodbye world!"
```

### The reactive_method decorator

Use the `@reactive_method` decorator to turn a non-reactive method into a reactive one.

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

    # Providing the names of the reactive values this method depends on tells
    # signified to monitor them for updates
    @reactive_method('items', 'tax_rate')
    def total(self):
        subtotal = sum(item.price for item in self.items.value)
        return subtotal * (1 + self.tax_rate)

items = [Item(name="Book", price=20), Item(name="Pen", price=4)]
cart = Cart(items)

total_price = cart.total()
print(total_price)  # 27 (24 * 1.125)
cart.tax_rate.value = 0.25
print(total_price)  # 30 (24 * 1.25)
cart.items[0] = Item(name="Rare book?", price=400)
print(total_price)  # 505 (404 * 1.25)

```

### Understanding `unref`

The `unref` function is particularly useful when working with values that might be either reactive or non-reactive. This is common when writing functions that should handle both types transparently.

```python
from signified import HasValue, Signal, unref

def process_data(value: HasValue[float]):
    # unref handles both reactive and non-reactive values
    actual_value = unref(value)
    return actual_value * 2

# Works with regular values
regular_value = 4
print(process_data(regular_value))  # 8

# Works with reactive values
reactive_value = Signal(5)
print(process_data(reactive_value))  # 10

# Works with nested reactive values
nested_value = Signal(Signal(Signal(6)))
print(process_data(nested_value))   # 12
```
