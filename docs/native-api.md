# Native kernels (C API)

Compiled extensions can create `Computed` values whose function is native code instead of a
Python callable. Signified tracks and refreshes them like any other `Computed`, but evaluating
one runs no Python, so a chain of native computeds avoids the interpreter between nodes. This is
for libraries that spend most of their time evaluating small reactive nodes, such as per-frame
math in an animation library. Most code does not need it.

## How it works

`signified._core` exports a capsule, `signified._core._C_API`, holding a table of functions. Its
`new_computed(cls, kernel, args)` returns an instance of `cls` (`Computed` or a subclass) that
behaves like `computed(f)(*args)`:

- On every evaluation, each `Signal`, `Computed` or `Binding` in `args` is replaced by its
  current value, and the computed depends on it. Other arguments are passed as they are.
- Evaluation is lazy: the kernel runs when the computed is read after an argument changed.
- The kernel also receives the computed's current value. Returning that same object reports an
  unchanged value, so nothing computed from it is recomputed (like a custom `equal`).
- An exception the kernel sets is cached and raised to readers, like one from a Python function.

From Python, a native computed is an ordinary `Computed`. With the example extension from the
repository (`rust/api-example`):

<!-- skip-test -->
```python
from signified import Computed, Signal
from signified_api_example import weighted_sum

a, b = Signal(1.0), Signal(2.0)
total = weighted_sum([2.0, 3.0], a, b)  # computed by a Rust kernel
doubled = Computed(lambda: total.value * 2)
a.value = 4.0
print(total.value, doubled.value)  # 14.0 28.0
```

## From Rust

The [`signified-api`](https://crates.io/crates/signified-api) crate describes the table and its
contract ([documentation](https://docs.rs/signified-api)). It has no dependencies and works with
pyo3 or raw FFI:

```rust
use pyo3::ffi;
use signified_api::{CApi, Kernel, CAPSULE_NAME};

let api = unsafe { ffi::PyCapsule_Import(CAPSULE_NAME.as_ptr(), 0) } as *const CApi;
let api: &'static CApi = unsafe { api.as_ref() }.expect("import signified first");
assert!(api.is_compatible());

let kernel = Kernel { call: my_kernel, ctx: Box::into_raw(context).cast(), release: Some(my_release) };
let computed = unsafe { (api.new_computed)(computed_class, kernel, args_tuple) };
```

[`rust/api-example`](https://github.com/dougmercer/signified/tree/main/rust/api-example) is a
complete extension with safe wrappers over these functions, built and tested in CI.

## From C

The table and kernel, as C declarations:

```c
typedef PyObject *(*signified_kernel_fn)(void *ctx, PyObject *const *args, Py_ssize_t nargs, PyObject *previous);
typedef void (*signified_release_fn)(void *ctx);

typedef struct {
    signified_kernel_fn call;
    void *ctx;
    signified_release_fn release; /* may be NULL */
} signified_kernel;

typedef struct {
    uint32_t version; /* 1 */
    uint32_t size;    /* sizeof the engine's table */
    PyObject *(*new_computed)(PyObject *cls, signified_kernel kernel, PyObject *args);
} signified_capi;

signified_capi *api = PyCapsule_Import("signified._core._C_API", 0);
```

## Contract

- **Thread state.** Every function in the table, and every kernel and release function, is
  called with an attached thread state (holding the GIL).
- **Threads.** A graph is used from one thread at a time but can move between threads, so a
  kernel never runs concurrently for one computed, but its context may be used from different
  threads over its life.
- **References.** A kernel's arguments and current value are borrowed for the call. It returns a
  new reference, or `NULL` with an exception set.
- **Release.** The release function runs once: when the computed is freed, or immediately if
  `new_computed` fails (it always takes ownership of the context). It can run while the
  interpreter is finalizing, when only reference counting is safe.
- **Garbage collection.** Python objects a context owns are invisible to the cyclic garbage
  collector, so they must not refer back to the computed.
- **Errors.** Kernels and release functions report errors by setting a Python exception; they
  must not unwind (in Rust, catch panics: one leaving an `extern "C"` function aborts the
  process).

## Compatibility

| signified          | API version |
|--------------------|-------------|
| 0.7.0 and earlier  | none        |
| later releases     | 1           |

A new API version only appends functions to the table, so code written for version `n` works with
every signified that exports version `n` or later. Check `version >= n` and that `size` is at
least the size of the table you were built against; the Rust crate's `CApi::is_compatible` does
both.
