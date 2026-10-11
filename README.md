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

```console
$ uv add signified
```

## Why care?

`signified` is a reactive programming library built around four reactive data structures:

- `Signal` stores a mutable value.
- `Computed` calculates a read-only value
- `Effect` runs an action when the values it reads change
- `Binding` is a stable handle that lets you switch between reactive values without rebuilding calculations that use it

This allows us to create a network of computation, where one value being modified can trigger other objects to update.

We can write more declarative code, like:

```python
x = Signal(3)
x_squared = x ** 2  # currently equal to 9
x.value = 10  # Will immediately notify x_squared, whose value will become 100.
```

Here, `x_squared` is a `Computed` object whose value is always equal to `x ** 2`. Neat!

In the above example, we generated the `Computed` object on-the-fly using overloaded Python operators like `**`, but we could have also written it using the `computed` decorator,

```python
from signified import computed

@computed
def power(x, n):
    return x**n

x_squared = power(x, 2)  # equivalent to the above
```

To make something *happen* when a value changes, we can use an effect:

```python
from signified import effect

@effect
def show(n):
    print(n)

watcher = show(x_squared)  # prints 100
x.value = 4                # prints 16
watcher.dispose()
```

Effects run once right away, then again whenever something they read changes until they are explicitly disposed or the effect is garbage collected.

In the above example, `x_squared` is wired to `x`. To swap what feeds a calculation without rebuilding it, use a `Binding` instead of Signal:

```python
from signified import Binding

y = Signal(5)
base = Binding(x)       # follows x, for now
cubed = power(base, 3)  # currently equal to 64

base.value = y  # cubed now follows y, and becomes 125
x.value = 10    # cubed ignores x now
```

A `Signal` can't do this. `signal.value = y` stores the `y` object itself, not its value.

Together, these data structures allow us to implement a wide variety of capabilities. In particular, I wrote this library to make my animation library `keyed` easier to maintain and more fun to work with.

## Ready to learn more?

Check out the docs at [https://dougmercer.github.io/signified](https://dougmercer.github.io/signified).
