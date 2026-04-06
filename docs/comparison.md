---
hide:
  - navigation
---

# Library Comparison

This page compares `signified` with two other Python reactive libraries: [`reaktiv`](https://github.com/buiapp/reaktiv) and [`param`](https://param.holoviz.org/). All three implement reactive programming, but they differ in API design, feature scope, and performance.

## Features At a Glance

| | signified | reaktiv | param |
|---|---|---|---|
| **Read a value** | `x.value` | `x()` | `x.rx.value` |
| **Write a value** | `x.value = v` | `x.set(v)` | `x.rx.value = v` |
| **Derived value (inline)** | `y = x * 2` | — | `y = x.rx() * 2` |
| **Derived value (decorator)** | `@computed` | `@Computed` | `@param.depends` |
| **React to changes** | `Effect(fn)` | `Effect(fn)` | `x.rx.watch(fn)` / `obj.param.watch(fn, ...)` |
| **Operator overloading** | Yes | No | Yes (via `obj.rx()`) |
| **Async support** | No | Yes | Yes |
| **Multithreading support** | No | Yes | No |

## API Comparison

Here is the same computation expressed in each library:

=== "signified"

    ```python
    from signified import Signal, Effect

    price = Signal(10.0)
    quantity = Signal(3)
    total = price * quantity      # Computed automatically via operator overload

    print(total.value)            # 30.0

    printer = Effect(lambda: print(f"Total: {total.value}"))

    price.value = 15.0            # prints "Total: 45.0"
    ```

=== "reaktiv"

    ```python
    from reaktiv import Signal, Computed, Effect

    price = Signal(10.0)
    quantity = Signal(3)
    total = Computed(lambda: price() * quantity())   # Explicit lambda

    print(total())                # 30.0

    printer = Effect(lambda: print(f"Total: {total()}"))

    price.set(15.0)               # prints "Total: 45.0"
    ```

=== "param"

    ```python
    from param import rx

    price = rx(10.0)
    quantity = rx(3)
    total = price * quantity      # Computed automatically via operator overload

    print(total.rx.value)         # 30.0

    total.rx.watch(lambda v: print(f"Total: {v}"))

    price.rx.value = 15.0         # prints "Total: 45.0"
    ```

### Key usability differences

**signified** overloads Python operators so reactive expressions can typically read like normal code (`price * quantity` returns a reactive `Computed` object). The `.rx` namespace handles some additional operations Python cannot easily overload, such as equality/identity testing.

**reaktiv** requires explicit `Computed(lambda: ...)` wrappers but, like signified, automatically tracks dependencies — every signal read inside the lambda is tracked.

**param** supports two reactive styles. The `rx` interface (shown above) allows standalone reactive values with operator overloading, similar to signified. The `Parameterized` class-based style provides rich metadata: type checking, bounds, documentation, and introspection. It integrates deeply with the HoloViz ecosystem (Panel, HoloViews).

## Performance

Benchmarks were run with [`signified-bench`](https://github.com/dougmercer/signified-bench) at commit `36e10c9edab4202dd30b5c2950b8cb6f29215eda` using `pytest-benchmark`.
The versions compared here were `signified==0.4.0`, `reaktiv==0.21.3`, and `param==2.3.3`, run on a MacBook M1 Max.
These numbers are meant to give a broad sense of performance rather than serve as a fully rigorous benchmark suite.
Results show median wall-clock time per scenario (lower is better).

### signified 0.4.0 vs reaktiv vs param

With 0.4.0, **signified and reaktiv are closely matched** in terms of single threaded performance. The amount of overhead either library would introduce is small compared to whatever work would typically be done within non-toy `computed` functions.

**`param` is significantly slower**.

| Scenario | signified 0.4.0 | reaktiv | param |
|---|---|---|---|
| `signal_read_write` | 8 ms | 7 ms | 204 ms |
| `multi_input_computed` | 26 ms | 36 ms | 421 ms |
| `shared_dependency_branches` | 26ms | 28 ms | 613 ms |
| `shared_clock_reads` | 47 ms | 49 ms | 1240 ms |
| `deep_chain_updates` | 120 ms | 134 ms | 1576 ms |
| `fanout_updates` | 206 ms | 236 ms | 3593 ms |
| `diamond_updates` | 224 ms | 257 ms | 3933 ms |
| `effect_fanout_updates` | 494 ms | 1501 ms | 3156 ms |

signified 0.4.0 is a substantial performance release. Across all scenarios it runs roughly **2.5–3× faster** than 0.3.2.

## Choosing a library

**Choose signified if** you want Pythonic syntax, operator overloading, and competitive performance. However, `signified` does not support async and is not threadsafe.

**Choose reaktiv if** you prefer an explicit, Angular-inspired API where every dependency is a function call, or if you need built-in async resource loading.

**Choose param if** you are building UI components in the HoloViz ecosystem (Panel, HoloViews).


## Other libraries that are not comparable to `signified`

`ReactiveX` (`rxpy`) works with processing asynchronous streams of data with operators. It is an inherently different computation model at its core, even if it looks similar at first glance.
