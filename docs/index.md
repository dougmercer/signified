# Signified

Keep Python values up to date as their inputs change.

## Quickstart

```bash
pip install signified
```

Wrap changing values in `Signal`, then use them in calculations:

```python
from signified import Signal

price = Signal(10)
quantity = Signal(2)
total = price * quantity

print(total.value)  # 20
quantity.value = 3
print(total.value)  # 30
```

`total` is a `Computed`: it remembers how to calculate its value and updates
when needed. You can also use your own functions with `@computed`.

## Where to start

- [Usage guide](usage.md): calculations, effects, containers, and switching inputs.
- [Playground](playground.md): try examples in your browser.
- [Library comparison](comparison.md): see how Signified relates to other libraries.
- [API reference](api.md): look up a class, function, or method.
