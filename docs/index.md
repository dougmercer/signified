# Significant

A Python library for reactive programming with kind-of working type hints.

## Getting started

```bash
pip install significant
```

## Why care?

`significant` is a reactive programming library that implements two primary data structures: `Signal` and `Computed`.

Both of these objects implement the *Observer* and *Observable* design patterns. This means that they can notify
other *Observers* if they change, and they can subscribe to be notified if another *Observable* changes.

This allows us to create a network of computation, where one value being modified can trigger other objects to update.

This allows us to write more declarative code, like,

```python
x = Signal(3)
x_squared = x ** 2  # currently equal to 9
x.value = 10  # Will immediately notify x_squared, whose value will become 100.
```

Here, `x_squared` became a reactive expression (more specifically, a `Computed` object) whose value is always equal to `x ** 2`. Neat!

`significant`'s `Signal` object effective gives us a container which stores a value, and `Computed` gives us a container to store the current value of a function. In the above example, we generated the Computed object on-the-fly using overloaded Python operators like `**`, but we could have just as easily done,

```python
from significant import computed

@computed
def power(x, n):
    return x**n

x_squared = power(x, 2)  # equivalent to the above
```

Together, these data structures allow us to implement a wide variety of capabilities. In particular, I wrote this library to make my to-be-released animation library easier to maintain and more fun to work with.

Hopefully you find it useful!
