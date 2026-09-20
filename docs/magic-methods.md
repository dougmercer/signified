# Operators

Operators on signals, computed values, and bindings create a `Computed`.
Read its `.value` to get the result:

```python
from signified import Signal

x = Signal(10)
result = x + 3
print(result.value)  # 13
x.value = 20
print(result.value)  # 23
```

## Unary methods

| Operation | Examples |
| --- | --- |
| Sign and absolute value | `-x`, `+x`, `abs(x)` |
| Bitwise inversion | `~x` |
| Rounding | `round(x)`, `round(x, 2)` |
| Integer rounding with `math` | `math.floor(x)`, `math.ceil(x)`, `math.trunc(x)` |

## Arithmetic and bitwise methods

Operands can be plain or reactive values. The values they hold must support
the operation, just as in ordinary Python.

| Operation | Examples |
| --- | --- |
| Arithmetic | `x + y`, `x - y`, `x * y`, `x / y`, `x // y`, `x % y`, `x ** y` |
| Quotient and remainder | `divmod(x, y)` |
| Matrix multiplication | `x @ y` |
| Bitwise operations | `x & y`, `x \| y`, `x ^ y`, `x << y`, `x >> y` |

## Reverse arithmetic and bitwise methods

Plain values can also appear on the left: `3 + x`, `50 / x`, `2 ** x`,
`divmod(50, x)`, `3 & x`, `3 | x`, `3 ^ x`, `1 << x`, `32 >> x`, and `matrix @ x`.

## Comparisons, predicates, and truthiness

`<`, `<=`, `>`, and `>=` produce reactive results.

`==` and `!=` do not. Comparisons between reactive objects use identity,
so they remain usable as distinct keys in sets and dictionaries. To compare
wrapped values reactively, use `x.rx.eq(y)` or `x.rx.ne(y)`.

Use `.rx` for the following operations:

| To calculate… | Use |
| --- | --- |
| Value equality | `x.rx.eq(y)` |
| Value inequality | `x.rx.ne(y)` |
| Object identity | `x.rx.is_(y)`, `x.rx.is_not(y)` |
| Membership | `x.rx.in_(items)`, `items.rx.contains(x)` |
| Truthiness | `x.rx.as_bool()` |
| Length | `items.rx.len()` |
| A conditional result | `condition.rx.where(when_true, when_false)` |

`==`, `!=`, `is`, `in`, `bool(x)`, and `len(x)` do not create these reactive
calculations. Python's `if`, `and`, and `or` also do not build reactive
expressions. Use `.rx.where(...)` to choose between values, or put ordinary
Python branching inside a `Computed` function that reads `.value`.

## Object and container access

`x.name`, `x[key]`, and `x(...)` create calculated values. Methods can be
chained, for example `text.strip().lower()`.

Only `Signal` forwards writes such as `x.name = value` and `x[key] = value`
to its stored object and sends updates. Attribute names must already exist.
Changes through the raw `.value` need an explicit `.update()` call; see
[Lists and dictionaries](usage.md#collections-and-item-assignment).

## Complete API reference

See the [operator API](api.md#magic-methods) for individual methods and the
[rx API](api.md#reactive-namespace) for additional operations.
