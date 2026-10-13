# signified-api example

A small Python extension, built with pyo3 and maturin, whose `weighted_sum` returns a
`signified.Computed` evaluated by a Rust kernel through [`signified-api`](../api). It is built like
a separate project would be: it imports signified's C API from the `signified._core._C_API`
capsule at run time.

`src/lib.rs` wraps the raw API in a few safe helpers (`api`, `NativeKernel`, `new_computed`) that
an extension can copy. CI builds it and runs `tests/`:

```console
uv pip install --no-deps ./rust/api-example
uv run --no-sync pytest rust/api-example/tests
```
