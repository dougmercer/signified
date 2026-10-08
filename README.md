# Signified

[![PyPI Downloads](https://static.pepy.tech/personalized-badge/signified?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/signified)
[![PyPI - Version](https://img.shields.io/pypi/v/signified)](https://pypi.org/project/signified/)
[![Tests Status](https://github.com/dougmercer/signified/actions/workflows/test.yml/badge.svg)](https://github.com/dougmercer/signified/actions/workflows/test.yml?query=branch%3Amain)
[![CodSpeed](https://img.shields.io/endpoint?url=https://codspeed.io/badge.json)](https://codspeed.io/dougmercer/signified?utm_source=badge)

---

**Documentation**: [https://dougmercer.github.io/signified](https://dougmercer.github.io/signified)

**Source Code**: [https://github.com/dougmercer/signified](https://github.com/dougmercer/signified)

---

A fast, fully-typed Python library for reactive programming.

## Getting started

First, [install `uv`](https://docs.astral.sh/uv/getting-started/installation/), and then add `signified` to your project:

```console
$ uv add signified
```

## Why care?

`signified` is a reactive programming library built around three data structures:

- `Signal[T]` stores a mutable value of any Python type `T`.
- `Computed[T]` calculates a read-only value of any Python type `T`.
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

Together, these data structures allow us to implement a wide variety of capabilities. In particular, I wrote this library to make my animation library `keyed` easier to maintain and more fun to work with.

## Ready to learn more?

Check out the docs at [https://dougmercer.github.io/signified](https://dougmercer.github.io/signified).
