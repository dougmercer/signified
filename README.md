# Signified

[![PyPI - Downloads](https://img.shields.io/pypi/dw/signified)](https://pypi.org/project/signified/)
[![PyPI - Version](https://img.shields.io/pypi/v/signified)](https://pypi.org/project/signified/)
[![Tests Status](https://github.com/dougmercer/signified/actions/workflows/test.yml/badge.svg)](https://github.com/dougmercer/signified/actions/workflows/test.yml?query=branch%3Amain)

---

**Documentation**: [https://dougmercer.github.io/signified](https://dougmercer.github.io/signified)

**Source Code**: [https://github.com/dougmercer/signified](https://github.com/dougmercer/signified)

---

A Python library for reactive programming (with kind-of working type narrowing).

## Getting started

```console
pip install signified
```

## Why care?

`signified` is a reactive programming library that implements two primary data structures: `Signal` and `Computed`.

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

`signified`'s `Signal` object effectively gives us a container which stores a value, and `Computed` gives us a container to store the current value of a function. In the above example, we generated the Computed object on-the-fly using overloaded Python operators like `**`, but we could have just as easily done,

```python
from signified import computed

@computed
def power(x, n):
    return x**n

x_squared = power(x, 2)  # equivalent to the above
```

Together, these data structures allow us to implement a wide variety of capabilities. In particular, I wrote this library to make my to-be-released animation library easier to maintain and more fun to work with.

## ... what do you mean by "kind of working type narrowing"?

Other reactive Python libraries don't really attempt to implement type hints (e.g., [param](https://param.holoviz.org/)).

``signified`` is type hinted and supports type narrowing even for nested reactive values.

```python
from signified import Signal

a = Signal(1.0)
b = Signal(Signal(Signal(2)))
reveal_type(a + b)  # Computed[float | int]
```

Unfortunately, for the time being, our type hints only work with ``pyright``.

## Ready to learn more?

Checkout the docs at [https://dougmercer.github.io/signified](https://dougmercer.github.io/signified) or watch [my YouTube video about the library](https://youtu.be/nkuXqx-6Xwc).
