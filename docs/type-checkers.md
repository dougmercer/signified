# Type Checkers

**Use Pyright for the best type inference with Signified.** Pyrefly is a usable
alternative with caveats.

Assessed on 2026-10-10 with Python **3.14.3** and Signified **0.7.0**
([revision 9de4e8b](https://github.com/dougmercer/signified/tree/9de4e8be17d0c16236ea988af9868accf6319005)).
The [inference suite](https://github.com/dougmercer/signified/blob/9de4e8be17d0c16236ea988af9868accf6319005/tests/type_inference.py)
checks 765 inferred types and 60 operations that should be rejected.

| Checker | Version | Wrong types (of 765) | Invalid operations flagged (of 60) | Recommendation |
| --- | --- | ---: | ---: | --- |
| **Pyright** | 1.1.414 | 0 | 60 | **Recommended** |
| **Pyrefly** | 1.3.2 | 33 | 42 | **Usable with caveats** |
| **ty** | 0.0.86 | 247 | 56 | Not recommended yet |
| **mypy** | 2.4.0 | 165 | 34 | Not recommended |

- **Pyrefly:** `abs`, `math.trunc`, `math.floor`, and `math.ceil` on signals
  infer `Unknown`, and `divmod` infers the wrong type for mixed, `Decimal`, or
  reflected operands. It accepts `round` and the `math` functions on
  unsupported values, and reports an error when calling a wrapped callable
  object.
- **ty:** `unref` and `Binding` rarely infer the right type, many operators
  infer `Unknown`, and some valid operations are rejected, such as
  `Signal(10.0) // Signal(2.0)`.
- **mypy:** `unref` and `Binding` reject valid arguments and infer `Never`.
  Operators on signals mostly infer correctly. Mypy ran with
  `--check-untyped-defs` so test bodies were checked.

Even with Pyright, attributes read through a signal, such as
`Signal(person).name`, and `deep_unref` results are typed `Any`, so a misspelled
attribute is not caught. Functions decorated with `@computed` or `@effect` keep
their return type but do not check their arguments.
