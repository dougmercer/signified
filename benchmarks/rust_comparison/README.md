# signified against Rust reactive libraries

The same graphs and operations in [reactive_graph](https://docs.rs/reactive_graph) (Leptos),
[sycamore-reactive](https://docs.rs/sycamore-reactive) and [salsa](https://docs.rs/salsa)
(`src/main.rs`), and in signified driven from Python (`signified_graphs.py`). It measures the
frameworks' own overhead: every node's function is trivial.

| Workload | Graph (N = 1000) | Operation |
|----------|------------------|-----------|
| chain    | source → c1 → … → cN, each `+1` | set the source, read cN |
| fan      | source → N leaves (`source + i`) → one sum | set the source, read the sum |
| layers   | 10 layers of 100, each node the sum of two in the layer before, then a sum | set the source, read the sum |
| cutoff   | source → `source * 0` → chain of N | set the source, read the tail (its value never changes) |
| create   | the chain | build it, read the tail once, free it |

Every library cuts propagation off at an equal value (sycamore through `create_selector`) and is
checked against the expected result before it is timed. Times are the best of 5 samples of about
100 ms.

## Running

```console
cd benchmarks/rust_comparison
cargo run --release                                  # all three, or name some: reactive_graph sycamore salsa
cargo run --release --bin reactive_graph_scaling     # chain update cost against chain length

cd ../..                                             # signified, from the repository root
uv sync --group test
uv pip install --no-deps ./rust/api-example          # for the native-kernel rows
uv run --no-sync python benchmarks/rust_comparison/signified_graphs.py
uv run --no-sync python benchmarks/rust_comparison/signified_graphs.py --node-kinds
```

`Cargo.lock` pins sycamore-reactive 0.9.3: 0.9.4 needs Rust 1.94.

## Results

Microseconds per operation, best of two runs; Apple M1 Max, Rust 1.93 (release, fat LTO),
CPython 3.14.7, 2026-10-12. Run-to-run differences were 1% (median) to 4%.

| µs per operation           | chain  | fan   | layers | cutoff | create |
|----------------------------|-------:|------:|-------:|-------:|-------:|
| sycamore-reactive 0.9.3    | 48     | 500   | 82     | 16     | 105    |
| salsa 0.28.5               | 231    | 198   | 250    | 77     | 348    |
| signified, Python functions | 191   | 203   | 212    | 50     | 1,860  |
| signified, native kernels  | 270    | 293   | 302    | 51     | 1,192  |
| reactive_graph 0.2.15      | 38,138 | 1,787 | 15,931 | 154    | 458    |

- signified's graph bookkeeping costs about 175 ns per node: a chain of identity functions takes
  176 µs per update (`--node-kinds`), so the functions themselves add little. That is on par with
  salsa, while every value is a Python object.
- sycamore propagates eagerly when a signal is set: fastest on deep chains, and it stops at the
  unchanged node in `cutoff`, where the lazy libraries (signified, salsa, reactive_graph) check the
  chain when it is read. With 1000 dependents of one signal (`fan`) it is slower than salsa and
  signified.
- reactive_graph's chain update is quadratic in the chain's length (about 2 µs per node at 50
  nodes, 29 µs at 800; see `reactive_graph_scaling`): a memo that recomputes marks everything
  downstream of it again (`computed/inner.rs`, `mark_dirty` and `mark_check`). Shallow graphs are
  unaffected.
- Creating nodes is signified's slowest operation, at 1.2–1.9 µs per node: each is a Python object
  (and here, a Python function).
- With functions this small, native kernels are slower than Python functions: the C API's
  evaluation path resolves arguments and allocates more per call than `computed(fn)` does
  (`--node-kinds` shows the engine's own test kernel at the same cost as the example's). Native
  kernels pay off when the function is expensive.
