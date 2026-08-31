# Signified

[![PyPI - Downloads](https://img.shields.io/pypi/dw/signified)](https://pypi.org/project/signified/)
[![PyPI - Version](https://img.shields.io/pypi/v/signified)](https://pypi.org/project/signified/)
[![Tests Status](https://github.com/dougmercer/signified/actions/workflows/test.yml/badge.svg)](https://github.com/dougmercer/signified/actions/workflows/test.yml?query=branch%3Amain)
[![CodSpeed](https://img.shields.io/endpoint?url=https://codspeed.io/badge.json)](https://codspeed.io/dougmercer/signified?utm_source=badge)

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

`signified` is a reactive programming library built around three data structures:

- `Signal` stores a mutable plain value.
- `Computed` calculates a read-only plain value.
- `Binding` is a stable handle that can switch between reactive sources.

This allows us to create a network of computation, where one value being modified can trigger other objects to update.

This allows us to write more declarative code, like,

```python
x = Signal(3)
x_squared = x ** 2  # currently equal to 9
x.value = 10  # Will immediately notify x_squared, whose value will become 100.
```

Here, `x_squared` became a reactive expression (more specifically, a `Computed` object) whose value is always equal to `x ** 2`. Neat!

`signified`'s `Signal` object gives us a container which stores a value, and `Computed` stores the current value of a function. In the above example, we generated the Computed object on-the-fly using overloaded Python operators like `**`, but we could have just as easily done,

```python
from signified import computed

@computed
def power(x, n):
    return x**n

x_squared = power(x, 2)  # equivalent to the above
```

Together, these data structures allow us to implement a wide variety of capabilities. In particular, I wrote this library to make my to-be-released animation library easier to maintain and more fun to work with.

## ... what do you mean by "kind-of working type narrowing"?

Other reactive Python libraries don't really attempt to implement type hints (e.g., [param](https://param.holoviz.org/)).

``signified`` is type hinted, including rebindable values.

```python
from signified import Binding, Signal

a = Signal(1.0)
b = Binding(Signal(2))
reveal_type(a + b)  # Computed[float]
```

Unfortunately, our type hints only work with ``pyright``.

## Ready to learn more?

Checkout the docs at [https://dougmercer.github.io/signified](https://dougmercer.github.io/signified) or watch [my YouTube video about the library](https://youtu.be/nkuXqx-6Xwc).
