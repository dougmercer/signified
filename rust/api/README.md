# signified-api

The C API of [signified](https://github.com/dougmercer/signified)'s reactive engine, for Python
extension modules that compute reactive values natively.

signified is a Python library of reactive values (`Signal`, `Computed`, `Effect`) with a compiled
engine, `signified._core`. Through this API, another extension creates a `signified.Computed`
whose value comes from a native function (a *kernel*) instead of a Python callable. The engine
tracks the computed's reactive arguments and refreshes it lazily like any other `Computed`, but
evaluating it runs no Python code, so chains of native computeds avoid the interpreter between
nodes. Python code reads and combines them like any other reactive value.

For example, [key3d](https://github.com/dougmercer/key3d) evaluates the animation and transform
nodes behind every animated object this way.

This crate describes the API: the `CApi` table that `signified._core` exports in the
`signified._core._C_API` capsule, the `Kernel` type and the contract they follow. It has no
dependencies, is `no_std`, and works with pyo3, raw `pyo3-ffi` or C.

```rust
use pyo3::ffi;
use signified_api::{CApi, Kernel, CAPSULE_NAME};

// Once, with an attached thread state: the table lives as long as the process.
let api = unsafe { ffi::PyCapsule_Import(CAPSULE_NAME.as_ptr(), 0) } as *const CApi;
let api: &'static CApi = unsafe { api.as_ref() }.expect("import signified first");
assert!(api.is_compatible());

// A computed whose value `sum(ctx, args, nargs, previous)` computes from `args`, a tuple whose
// Signals and Computeds it reads (and so depends on) on every evaluation.
let kernel = Kernel { call: sum, ctx: Box::into_raw(context).cast(), release: Some(release) };
let computed = unsafe { (api.new_computed)(computed_class, kernel, args) };
```

See the [crate documentation](https://docs.rs/signified-api) for the contract (thread state,
references, when the context is released, garbage collection), and
[`rust/api-example`](https://github.com/dougmercer/signified/tree/main/rust/api-example) for a
complete extension with safe wrappers, tested in CI.

## Compatibility

| signified (Python) | API version | signified-api crate |
|--------------------|-------------|---------------------|
| 0.7.0 and earlier  | none        |                     |
| later releases     | 1           | 0.1                 |

New API versions only append fields to `CApi`, so an extension built against version `n` works
with every signified that exports version `n` or later. `CApi::is_compatible()` checks this.

## License

BSD-3-Clause, like signified.
