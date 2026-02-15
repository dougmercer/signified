# Signified

A Python library for reactive programming (with type narrowing).

`signified` is built around two core types:

- `Signal[T]`: mutable reactive state
- `Computed[T]`: derived reactive state

If you update a `Signal`, dependent `Computed` values update automatically.

## Why Care?

Both `Signal` and `Computed` participate in Observer/Observable behavior:

- reactive values can subscribe to upstream values
- upstream changes notify and propagate through dependent computations

That gives you declarative expressions that stay current:

```python
from signified import Signal

x = Signal(3)
x_squared = x ** 2

print(x_squared.value)  # 9
x.value = 10
print(x_squared.value)  # 100
```

You can build the same thing with `@computed`:

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

## Quickstart

```bash
pip install signified
```

```python
from signified import Signal

price = Signal(10)
quantity = Signal(2)
total = price * quantity

print(total.value)  # 20
price.value = 15
print(total.value)  # 30
```

## Mental Model

1. Wrap changing data in `Signal`.
2. Build derived values with operators or `@computed`.
3. Read reactive outputs from `.value`.
4. Update the `.value` of signals to trigger updates.

## Start Here

- New to the library: [Usage Guide](usage.md)
- Full API docs: [Core API](api/core.md)
- Quick look at avilable operators: [Magic Methods and Operators](magic-methods.md)
- Extending `signified` with plugins: [Plugins](plugins.md)
