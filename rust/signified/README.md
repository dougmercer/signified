# signified (Rust)

Reactive values for Rust programs: `Signal<T>`, `Computed<T>` and `Effect`, on the same graph
engine (`signified-engine`) as the Python library [signified](https://github.com/dougmercer/signified).

```rust
use signified::{Computed, Effect, Signal};

let width = Signal::new(2.0);
let height = Signal::new(3.0);
let area = Computed::new({
    let (width, height) = (width.clone(), height.clone());
    move || width.get() * height.get()
});
let _log = Effect::new({
    let area = area.clone();
    move || println!("area is {}", area.get())
}); // prints "area is 6"
width.set(4.0); // prints "area is 12"
```

- Values are ordinary Rust types; one graph mixes them. `get()` needs `Clone`; `with(|v| ...)`
  borrows instead.
- Computeds are lazy and cut off propagation at an equal value (`PartialEq`, or the equality
  given to `Computed::new_with_equal`).
- Dependencies are whatever a computed or effect read on its last run.
- `batch` defers effects; `untracked` reads without subscribing.
- Handles are reference counted and neither `Send` nor `Sync`: each thread has its own graph.
- A panic in a computed or effect leaves the graph consistent and continues where the value was
  read or the write happened. Cycles panic.
- The crate forbids `unsafe` code.

## How it relates to the Python library

`signified-engine` is generic over a `Host` that decides what a node's value is and how it is
evaluated. The Python extension is one host (values are Python objects); this crate is another
(values are typed slots behind a trait object). Each host gets its own compiled copy of the
engine, so neither pays for the other's types.

Nodes from the two hosts do not mix: a Rust graph and a Python graph are separate graphs, even in
one process. Rust code that computes values for Python graphs uses the C API
([`signified-api`](../api)) instead.

## Status

Exploratory, and not published. See `benchmarks/rust_comparison` for its speed next to
sycamore-reactive, salsa and reactive_graph.
