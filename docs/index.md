# Signified

A fast, fully-typed Python library for reactive programming.

```bash
pip install signified
```

## Values that *reactively* stay up to date

Ordinary Python assignment takes a snapshot:

```python
price = 10
quantity = 2
total = price * quantity  # 20

quantity = 3
print(total)  # still 20
```

`total` holds the number that `price * quantity` produced at that moment.
If price or quanity change, you have to remember to recalculate `total`,
along with anything calculated from `total`, and anything else calculated using
*those* values. In a large program, that bookkeeping can easily miss something.

**Reactive programming** removes that bookkeeping. You describe how values
depend on one another and `signified`
works out what needs to be recalculated when an input changes.

## Signals

In Signified, a value you plan to change goes in a **signal**. When a
calculation reads a signal, Signified records that the calculation depends on
it, so changing the signal marks those results as out-of-date.

Here is the example above written with signals:

```python
from signified import Signal

price = Signal(10)
quantity = Signal(2)
total = price * quantity

print(total.value)  # 20
quantity.value = 3
print(total.value)  # 30
```

`price` and `quantity` are signals. Multiplying them does not produce a number;
it produces a `Computed`, a calculation that follows both inputs. Read any of
them with `.value`, and change a signal by assigning to its `.value`.

## The building blocks

| Type | What it is | Example |
| --- | --- | --- |
| `Signal` | A value you can change | the price, the quantity |
| `Computed` | A calculation that follows its inputs | the total |
| `Effect` | An action that runs when the values it reads change | printing the total |
| `Binding` | A reactive value whose source you can switch without rebuilding the calculations that use it | choosing which item's price to show |

Python operators, attribute access, and method calls on reactive values create
`Computed` values for you. For your own functions, use `@computed`:

```python
from signified import Signal, computed

@computed
def with_tax(amount: float, rate: float) -> float:
    return round(amount * (1 + rate), 2)

price = Signal(10)
quantity = Signal(2)
tax_rate = Signal(0.08)

total = with_tax(price * quantity, tax_rate)
print(total.value)  # 21.6
tax_rate.value = 0.1
print(total.value)  # 22.0
```

`@computed` makes it so the function receives ordinary values and returns a reactive result, but callers can pass signals, computed values, or plain values.

`Computed` objects answer *what a value is*, but when something should *happen* on a change, use an effect. Effects run once immediately, then again whenever the values it depends on have changed:

```python
from signified import effect

@effect
def show(total: float) -> None:
    print(f"Total: ${total:.2f}")

watcher = show(total)  # Total: $22.00
quantity.value = 5     # Total: $55.00
watcher.dispose()      # stop watching
```

## How updates happen

Signified tries to keep things simple:

- **Dependencies come from reads.** A calculation depends on the reactive values it reads while it runs, and nothing else.
- **Calculations are lazy and cached.** A `Computed` runs when its value is needed, then saves the result until one of its inputs changes.
- **Effects are for actions.** When something should *happen* on a change, such as updating a display or writing a log, use an [effect](usage.md#run-actions-when-values-change) instead of a calculation.

[How updates work](compute-contract.md) covers these rules in detail, including equality, batching, and errors.

Signified also carries type hints through these expressions, so your editor knows that `total.value` is a `float`. For maximum compatibility use `pyright`. For more details on current limitations refer to the [type checker guide](type-checkers.md).

## Where to go next

- [Usage guide](usage.md): calculations, effects, containers, and switching inputs.
- [Playground](playground.md): try examples in your browser.
- [Library comparison](comparison.md): how Signified relates to other libraries.
- [API reference](api.md): details on every class, function, or method.
