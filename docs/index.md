---
hide:
  - navigation
---
# Signified

A Python library for reactive programming (with kind-of working type narrowing).

## Quickstart

```bash
pip install signified
```

## Why Care?

`signified` is built around two core types:

- ``Signal``: mutable reactive state
- ``Computed``: derived reactive state

If you update a `Signal`, dependent `Computed` values update automatically.

`Signal` and `Computed` follow both the `Observer` and `Observable` design patterns:

- reactive values can subscribe to upstream values
- upstream changes notify and propagate through dependent computations

That allows you to write declarative expressions that stay up-to-date, even as underlying values change:

```python
from signified import Signal

x = Signal(3)
x_squared = x ** 2

print(x_squared.value)  # 9
x.value = 10
print(x_squared.value)  # 100
```

Above, we used `signified`'s rich set of overloaded operators build a `Computed` object on-the-fly.

Alternatively, you can accomplish the same thing with `@computed`:

```python
from signified import Signal, computed

@computed
def power(base, exponent):
    return base ** exponent

x = Signal(3)
x_squared = power(x, 2)

print(x_squared.value)  # 9
x.value = 10
print(x_squared.value)  # 100
```

## Mental Model

1. Wrap changing data in `Signal`.
2. Build derived values with overloaded Python operators or `@computed`.
3. Read reactive outputs from `.value`.
4. Update the `.value` of `Signal`s to trigger updates.

## Ready to learn more?

- Read this first: [Usage Guide](usage.md)
- Full API docs: [Core API](api.md)
- Quick look at avilable operators: [Magic Methods and Operators](magic-methods.md)
- Extending `signified` with plugins: [Plugins](plugins.md)
