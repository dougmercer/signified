# Usage Examples

## Simple Arithmetic

```python
from significant import Signal

a = Signal(3)
b = Signal(4)

c = (a ** 2 + b ** 2) ** 0.5

assert c.value == 5

a.value = 5
b.value = 12

assert c.value == 13
```

## A Computed Function

```python
from significant import Signal, computed

a = Signal(3)

@computed
def pow(x: int, n: int) -> int:
    return x ** n

a_squared = pow(a, 2)

assert a_squared.value == 9

a.value = 5

assert a_squared.value == 25
```
