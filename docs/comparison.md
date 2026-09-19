# Library comparison

Signified keeps calculated Python values up to date when their inputs change.
Here is how its everyday API compares with two other Python libraries.

## Python libraries

In each row, `x` starts at `1` and `doubled` calculates twice its value.
Imports are omitted.

| Library | Create | Read / write | Calculate |
| --- | --- | --- | --- |
| Signified | `x = Signal(1)` | `x.value` / `x.value = 2` | `doubled = x * 2` |
| [reaktiv](https://reaktiv.readthedocs.io/en/latest/) | `x = signal(1)` | `x()` / `x.set(2)` | `doubled = computed(lambda: x() * 2)` |
| [Param](https://param.holoviz.org/en/docs/latest/user_guide/Reactive_Expressions.html) | `x = rx(1)` | `x.rx.value` / `x.rx.value = 2` | `doubled = x * 2` |

Signified and reaktiv track the reactive values read during a calculation.
Param's reactive expressions record operations and their inputs. If you are
already using Param parameters, its expressions and bound functions connect
to that model. See the [Param guide](https://param.holoviz.org/en/docs/latest/user_guide/Reactive_Expressions.html)
and [reaktiv introduction](https://reaktiv.readthedocs.io/en/latest/) for examples.

## What to expect from Signified

- Use Python operators and methods to build calculations, or `@computed` for
  your own functions.
- Calculations run when needed and save their results between changes.
- Use `Binding` when existing calculations should switch to another input.
- Changes through raw lists, dictionaries, and objects need an explicit update.
- Effects run in the current call; `batch()` delays them until its block exits.
  Keep reactive work on one thread.

The [usage guide](usage.md) shows these patterns. [How updates work](compute-contract.md)
covers equality, timing, and errors in detail.

## Coming from JavaScript signals

The ideas of state, calculated values, and effects may be familiar. In Signified,
you control effect lifetime: retain the effect object and call `.dispose()`
when finished. Do not assume a UI component will manage it for you.

Also check how nested objects are handled. Storing a list or dictionary in a
signal does not make every change inside it observable. See
[Lists and dictionaries](usage.md#collections-and-item-assignment).

## Detailed comparison

The [September 2026 comparison](articles/reactivity-comparison-2026-09-19.md)
preserves the longer, sourced survey of these libraries alongside Angular,
Vue, Svelte, Preact Signals, Solid, and MobX. Use it when porting code or
investigating differences in scheduling and error handling; it describes the
versions and sources reviewed at that time.
