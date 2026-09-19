# Type Checkers

**Use Pyright for the best type inference with Signified.** Pyrefly is a usable
alternative with caveats.

Assessed on 2026-09-19 with Python **3.12.12** and Signified **0.6.0**
([revision e55aaaa](https://github.com/dougmercer/signified/tree/e55aaaac328fa3a98299afcb9343f2f6424e9bb4)).

| Checker | Version assessed | Recommendation |
| --- | --- | --- |
| **Pyright** | **1.1.414** | **Recommended.** Passes the full inference suite. |
| **Pyrefly** | **1.3.1** | **Usable with caveats.** Core APIs infer well, but some `abs`, `round`, and `divmod` operations on signals infer incorrectly or fail checking. Wrapped callable objects also trigger errors. |
| **ty** | **0.0.82** | **Not recommended yet.** `unref`, `Binding`, and operators frequently infer incorrect unions, `Unknown`, or `Any`. |
| **mypy** | **2.3.1** | **Not recommended for Signified inference.** `unref`, `Binding`, and reactive operators frequently produce errors or lose type precision. |

The [264-assertion inference suite](https://github.com/dougmercer/signified/blob/e55aaaac328fa3a98299afcb9343f2f6424e9bb4/tests/type_inference.py), checked against an installed build, produced **0 / 15 / 154 / 265 diagnostics** respectively, including assertion mismatches and rejected calls. Mypy used `--check-untyped-defs` so test bodies were checked.

Even with Pyright, arbitrary proxy attributes and `deep_unref` lose precision to
`Any`, and `@computed` / `@effect` do not check argument types.
