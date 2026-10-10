# Rust Core Results

`signified.Signal`, `Computed`, `Binding` and `Effect` now run on a Rust core (`signified._core`); the Python engine is gone. Compared with `main`, as of Part 3:

- **Local CodSpeed suite:** 4.3× faster (geometric mean of 32 benchmarks), up to 9.7×; none slower. CodSpeed in CI reported ×3.6 for Part 2.
- **Per extra node in a chain:** 2.03 µs → 0.19 µs (10.9×). A 500-leaf frame: 2.31 ms → 0.27 ms (8.7×).
- **key3d `moving` scene:** 40.4 → 32.5 ms per frame (−20%, same session), with byte-identical output in all four benchmark scenes. key3d's test suite passes unchanged (1004 passed, 1 skipped).
- **Tests:** the suite passes on 3.12, 3.13 and 3.14 (also `-X dev` with unraisable exceptions as errors).

## Part 3: Rust-native data structures, fewer compatibility quirks (2026-10-10)

- **Commits:** `38a9896` (engine rework and behavior changes), `f3396c6` (native `unref`, `is_reactive`, `untracked`, `batch`, `Signal.at`), `1acd49b` (reactivity checked by class)

### Behavior changes

These were compatibility quirks of the Python engine:

- `subscribe()` observers run after a change has finished propagating, queued with effects (so `batch()` defers them too), instead of in the middle of it. Repeated notifications to one subscription before it runs are combined.
- A signal written twice while a change propagates notifies both times. Before, the second write was swallowed and a dependent computed could stay stale for good (reproduced on `main`).
- Overriding `notify()` or `update()` in a subclass raises `TypeError` at class creation; the engine does not call those overrides.
- Copying a `Signal`, `Computed` or `Binding` raises `TypeError` (instances using `tracked_fields` still copy and pickle).
- Reading or writing a `Signal` whose `__init__` never ran raises `RuntimeError`.
- Hooks run while a plugin is registered with `plugin_manager`; `SIGNIFIED_ENABLE_HOOKS` and `HOOKS_ENABLED` are gone.
- `is_reactive` is true for instances of the engine's classes; the `_IS_REACTIVE` class attribute is no longer consulted.

### Internals

- **Edges.** A dependency link records its slot in the source's observer list, and that entry records the link's position, so unsubscribing is O(1). Removed entries leave vacant slots until the list compacts, which keeps notification order. A freed consumer unsubscribes immediately instead of being pruned later.
- **Lookup.** While a consumer runs, each source it has read records where its link is, so a read finds its link without a search or a hash (the technique Preact signals uses). This replaced a read-order cursor and a hash index.
- **Notification.** The walk runs no Python code now that observers are queued, so it iterates the observer lists in place instead of copying them, and the per-wave hash set is gone.
- **Effects** record their queued state and run counts on the node instead of in hash maps.
- **Memory.** Nodes are `Rc` instead of `Arc` (the GIL already serializes access), and signal nodes no longer carry computed and effect state.
- **Native helpers.** `Binding` reads its holder and source in Rust. `unref` and `is_reactive` are native functions, and `untracked()`, `batch()` and `Signal.at()` return native context managers instead of generator-based ones.

A randomized test (`tests/engine/test_churn.py`) churns dynamic dependencies, subscriptions and freed consumers and checks every value and observer count; it fails when compaction stops updating link slots.

### Results

`benchmarks/per_node.py --compare` (other = `main`):

```
                              other       this  speedup
    cached Computed read      133ns       54ns     2.5x
     write+read, chain 1     2049ns      373ns     5.5x
     write+read, chain 4     6672ns      896ns     7.4x
    write+read, chain 16     24.5us     3139ns     7.8x
    write+read, chain 64    134.9us     12.0us    11.2x
          per extra node     2033ns      187ns    10.9x
    build+read, chain 64    224.9us     45.6us     4.9x
          500-leaf frame   2310.0us    266.7us     8.7x
```

Local CodSpeed suite (walltime, best round):

| Benchmark | main (Python engine) | Rust core | speedup |
| --- | ---: | ---: | ---: |
| `signal_create` | 855ns | 198ns | 4.3x |
| `signal_read` | 123ns | 90ns | 1.4x |
| `signal_write` | 477ns | 147ns | 3.3x |
| `signal_update` | 286ns | 127ns | 2.2x |
| `computed_create` | 1.08us | 322ns | 3.4x |
| `computed_read` | 171ns | 92ns | 1.9x |
| `computed_propagation` | 1.87us | 377ns | 5.0x |
| `computed_invalidate` | 2.51us | 402ns | 6.2x |
| `computed_decorator` | 4.33us | 717ns | 6.0x |
| `operator_chain` | 13.09us | 2.14us | 6.1x |
| `binding_chain_read` | 172ns | 93ns | 1.8x |
| `unref` | 159ns | 86ns | 1.9x |
| `binding_unref` | 208ns | 98ns | 2.1x |
| `deep_unref_dict` | 1.86us | 1.76us | 1.1x |
| `deep_computed_container` | 170ns | 94ns | 1.8x |
| `effect_creation` | 4.16us | 1.91us | 2.2x |
| `effect_fanout_updates` | 24.18ms | 3.82ms | 6.3x |
| `deep_chain_updates` | 1.25ms | 135.54us | 9.2x |
| `fanout` | 3.90ms | 416.18us | 9.4x |
| `diamond_updates` | 32.89ms | 3.50ms | 9.4x |
| `animation_stack` | 25.79ms | 3.80ms | 6.8x |
| `multi_input_computed` | 2.07ms | 357.28us | 5.8x |
| `stacked_layers` | 25.39ms | 2.62ms | 9.7x |
| `shared_clock_reads` | 16.92ms | 2.71ms | 6.2x |
| `dynamic_dependency_switch` | 3.87ms | 473.69us | 8.2x |
| `shared_dependency_branches` | 8.07ms | 1.05ms | 7.7x |
| `computed_signal_at` | 6.12ms | 1.14ms | 5.3x |
| `scoped_context_reads` | 9.87ms | 1.81ms | 5.4x |
| `subscription_churn` | 17.66ms | 3.54ms | 5.0x |
| `build_deep_chain` | 550.58us | 109.01us | 5.1x |
| `build_fanout_graph` | 1.07ms | 179.40us | 6.0x |
| `build_diamond_graph` | 2.22ms | 388.11us | 5.7x |

Geometric mean speedup: 4.29× over the 32 benchmarks (3.39× after Part 2). None is slower than `main`. The smallest gains are `deep_unref_dict` (1.1×, still a Python function) and `signal_read` (1.4×, mostly the benchmark's own lambda call).

key3d, same machine and session, `--frames 48 --repeat 5`: `moving` 40.44 ms per frame on `main`, 32.48 ms on this branch. The four-scene run against `main`'s saved fingerprints: `street` 18.85, `moving` 32.90, `textured` 9.30, `instanced` 4.33 ms per frame, all with identical output. key3d's test suite: 1004 passed, 1 skipped.

## Part 2: the public classes on the Rust core (2026-10-10)

Numbers in this part are for `04d17c8`–`dbee1b0`; Part 3 supersedes them.

- **Machine:** Apple M1 Max (10 cores, 64 GB), macOS 26.2, arm64; CPython 3.14.3 unless noted
- **Commits:** `04d17c8` (engine and classes), `417c207` (docs and typing declarations, benchmark), `dbee1b0` (review fixes)
- **Baseline:** `main` at `9e1050a`, installed in a separate virtualenv

### What moved

The Rust core owns all graph state and the whole propagation algorithm: dependency tracking, invalidation, refresh, custom `equal`, `Binding`'s restore after `at()`, the effect queue (`batch`, flush order, the 100-run limit, `ExceptionGroup`), plugin hooks and migration warnings. The public classes in `_reactive.py` subclass the native base classes together with `_ReactiveMixIn`, so operators, the attribute proxy, `.rx`, typing and docs stay in Python, as do `Signal.at`, item assignment, `Binding`'s source selection and `batch()`.

Native classes accept any arguments in `__new__` and initialize in `__init__`, so subclasses can chain `super().__init__()` (the prototype's open issue). Subclasses that override `notify` or `update` have them called (see Review).

### Tests

| Run | Result |
| --- | --- |
| CPython 3.14.3 (`uv run pytest`) | 454 passed |
| CPython 3.14.3, `-X dev`, unraisable exceptions as errors | 454 passed |
| CPython 3.13.12 and 3.12.12, unraisable exceptions as errors | 454 passed each |
| `SIGNIFIED_ENABLE_HOOKS=1` | passed |
| CI (Linux, 3.12–3.14), `type checks`, `ruff` | passed (on `417c207`) |

454 = `main`'s 407, minus the `Signal.__setattr__` doctest (its example moved into the `Signal` class docstring, since `__setattr__` is native now), plus 48 engine tests in `tests/engine/`. Tests that reached into the Python engine now use the native equivalents: `x._deps` for `x._impl._deps`, `x._observer_count() == 0` for `not x._observers`, and `monkeypatch.setattr(_core.config, "hooks", ...)` for patching `_reactive.HOOKS_ENABLED` and `_reactive.plugin_manager`. A script that records every plugin hook event (creation, reads, writes, `Binding.at`, `Signal.at`, effects, `invalidate`) produces the same trace on `main` and on this branch.

### Review

A fresh review of `04d17c8..417c207` probed about 45 scenarios under both engines (effects, batches, `Binding`, `at()`, custom `equal`, observers, hooks, migration warnings, tracked fields, cycles, cached errors, GC and `__del__` re-entrancy, deep graphs) and found the port faithful, with no borrow-rule violations, panics or leaks. It found two regressions, fixed in `dbee1b0` with tests:

- **Subclass overrides of `notify` and `update` were bypassed** by the native write, forwarding, invalidation and effect paths. The engine now calls them: a class that overrides `notify` has it called whenever the node notifies, and a consumer whose class overrides `update` (or, for a computed, `notify`) subscribes as a Python observer. Instances of the library's own classes take the native path.
- **`copy.copy` and `copy.deepcopy` raised `TypeError`.** A copy is now a new, independent node: a `Signal` copy holds the value (deep-copied for `deepcopy`); a `Computed` copy has the same function and computes on its first read; a `Binding` copy follows a copy of its source. On `main`, deep-copying a `Computed` or `Binding` produced an object that never updated again.

Differences from `main` that remain, all minor: `Variable()` can be instantiated (it is no longer an ABC); calling `__init__` again on a live signal replaces its value without notifying; `Signal.__new__(Signal)` gives a usable signal holding `None`, and `Computed.__new__(Computed).value` raises `RuntimeError`; cached exceptions carry shorter tracebacks (fewer Python frames); deep graphs go much deeper before `RecursionError` (about 7,000–10,000 operator nodes instead of about 200); `object.__setattr__` on a `Signal` raises `TypeError`, since the class defines `__setattr__` natively.

### Per-node benchmark

`uv run python benchmarks/per_node.py --compare <main venv>/bin/python`:

```
                              other       this  speedup
    cached Computed read      137ns       55ns     2.5x
     write+read, chain 1     2073ns      482ns     4.3x
     write+read, chain 4     6733ns     1376ns     4.9x
    write+read, chain 16     24.4us     4831ns     5.1x
    write+read, chain 64    129.5us     18.4us     7.0x
          per extra node     2069ns      280ns     7.4x
    build+read, chain 64    222.8us     45.1us     4.9x
          500-leaf frame   2369.1us    397.9us     6.0x
```

("other" is `main`.) The integrated core is faster than the prototype was (0.34 µs per node, 0.51 ms per frame): the classes are frozen, `Signal.__setattr__` is native, and a dependency lookup first checks the position the previous refresh read it at.

### CodSpeed suite, locally

`pytest tests/test_benchmarks.py --codspeed` (walltime, best round) under `main` and under this branch:

| Benchmark | main (Python engine) | Rust core | speedup |
| --- | ---: | ---: | ---: |
| `signal_create` | 855ns | 215ns | 4.0x |
| `signal_read` | 123ns | 91ns | 1.3x |
| `signal_write` | 477ns | 163ns | 2.9x |
| `signal_update` | 286ns | 142ns | 2.0x |
| `computed_create` | 1.08us | 318ns | 3.4x |
| `computed_read` | 171ns | 93ns | 1.8x |
| `computed_propagation` | 1.87us | 515ns | 3.6x |
| `computed_invalidate` | 2.51us | 409ns | 6.2x |
| `computed_decorator` | 4.33us | 718ns | 6.0x |
| `operator_chain` | 13.09us | 2.05us | 6.4x |
| `binding_chain_read` | 172ns | 93ns | 1.9x |
| `unref` | 159ns | 127ns | 1.2x |
| `binding_unref` | 208ns | 128ns | 1.6x |
| `deep_unref_dict` | 1.86us | 1.72us | 1.1x |
| `deep_computed_container` | 170ns | 92ns | 1.8x |
| `effect_creation` | 4.16us | 1.95us | 2.1x |
| `effect_fanout_updates` | 24.18ms | 6.55ms | 3.7x |
| `deep_chain_updates` | 1.25ms | 217.24us | 5.7x |
| `fanout` | 3.90ms | 668.21us | 5.8x |
| `diamond_updates` | 32.89ms | 5.70ms | 5.8x |
| `animation_stack` | 25.79ms | 5.65ms | 4.6x |
| `multi_input_computed` | 2.07ms | 456.77us | 4.5x |
| `stacked_layers` | 25.39ms | 3.86ms | 6.6x |
| `shared_clock_reads` | 16.92ms | 3.60ms | 4.7x |
| `dynamic_dependency_switch` | 3.87ms | 669.93us | 5.8x |
| `shared_dependency_branches` | 8.07ms | 1.62ms | 5.0x |
| `computed_signal_at` | 6.12ms | 2.33ms | 2.6x |
| `scoped_context_reads` | 9.87ms | 3.43ms | 2.9x |
| `subscription_churn` | 17.66ms | 8.68ms | 2.0x |
| `build_deep_chain` | 550.58us | 106.97us | 5.1x |
| `build_fanout_graph` | 1.07ms | 184.16us | 5.8x |
| `build_diamond_graph` | 2.22ms | 388.93us | 5.7x |

Geometric mean speedup: 3.39× over the 32 benchmarks. The smallest gains are `deep_unref_dict` (1.1×), `unref` (1.2×) and `signal_read` (1.3×): `deep_unref` and `unref` are still Python functions, and a bare read is mostly the cost of the benchmark's own lambda call.

### key3d

`benchmarks/frame_throughput.py --frames 48 --repeat 3` in key3d's 3.12 virtualenv, with `main`'s or this branch's `src` first on `sys.path` (`--save` under `main`, `--compare` under this branch):

| Scene | `main` ms/frame | Rust core ms/frame | First frame (`main` → Rust) | Output |
| --- | ---: | ---: | --- | --- |
| `street` | 19.43 | 19.01 | 1628 → 1429 ms | identical |
| `moving` | 40.92 | 34.15 | 1071 → 659 ms | identical |
| `textured` | 9.97 | 9.35 | 538 → 273 ms | identical |
| `instanced` | 4.46 (min 4.39) | 5.01 (min 4.42) | 92 → 84 ms | identical |

`moving` is the scene where every object moves every frame; the earlier profile put about 9 ms of its frame in signified's bookkeeping, and about 7 ms of that is gone. `instanced`'s mean is noise from one slow pass; the minimums match.

### Before a release

- **Packaging.** `publish.yml` still runs `uv build`, which now produces one platform-specific wheel plus an sdist that needs a Rust toolchain to install. It needs `PyO3/maturin-action` builds of abi3-py312 wheels for Linux (x86_64 and aarch64, manylinux and musllinux), macOS (x86_64 and arm64) and Windows x64. Pyodide needs a decision: an emscripten build, or unsupported.
- **Other workflows.** `test`, `type checks` and CodSpeed build the extension on `ubuntu-latest`, which ships Rust. `docs` builds the package too, and should keep working for the same reason; it only runs on `main` and tags, so it has not run on this branch.
- **Free-threaded Python.** The module declares `gil_used = true`, so a free-threaded interpreter turns the GIL back on when it imports signified.
- **Tuning.** Done in Part 3, except `deep_unref`, which is still Python.

## Part 1: prototype (2026-10-09)

The Rust core alongside the Python engine, measured side by side (plan of 2026-10-09, Tasks 1–6).


- **Date:** 2026-10-09
- **Commits measured:** `d9335d6` (engine, Task 3) and `e92454f` (review fix), branched from `main` at `9e1050a`
- **Machine:** Apple M1 Max (10 cores, 64 GB), macOS 26.2 (25C56), arm64
- **Python:** CPython 3.14.3 (uv-managed `.venv`); 3.12.12 for the 3.12 run
- **Toolchain:** rustc 1.93.0, PyO3 0.29.3 (`abi3-py312`), maturin release build via `uv sync`

### Benchmark

`uv run python benchmarks/per_node.py`, exactly as printed:

```
                             python       rust  speedup
    cached Computed read      136ns       56ns     2.4x
     write+read, chain 1     2010ns      676ns     3.0x
     write+read, chain 4     6693ns     1747ns     3.8x
    write+read, chain 16    25177ns     5887ns     4.3x
    write+read, chain 64   133166ns    22269ns     6.0x
          per extra node     2077ns      336ns
          500-leaf frame     2342us      504us     4.6x
```

A second run was within 3% of this one (per extra node 343 ns, 500-leaf frame 507 µs). Both match the prototype's numbers in the plan (0.34 µs per node, 0.51 ms per frame).

### Tests (Task 3)

| Run | Command | Result |
| --- | --- | --- |
| CPython 3.14.3 | `uv run pytest tests/engine -o addopts="" -q -W error::pytest.PytestUnraisableExceptionWarning` | 67 passed |
| CPython 3.14.3, `-X dev` | `uv run python -X dev -m pytest tests/engine -o addopts="" -q` | 67 passed |
| CPython 3.12.12 | `.venv-3.12/bin/python -m pytest tests/engine -o addopts="" -q -W error::pytest.PytestUnraisableExceptionWarning` | 67 passed |
| Full suite, 3.14.3 | `uv run pytest -q` | 474 passed (407 existing + 67 engine tests) |

pyright: 0 errors. ruff check and format: clean. `cargo fmt --check` and `cargo clippy --release -- -D warnings`: clean.

### Review fix (`e92454f`)

The whole-branch review found one engine-parity bug. `notify` added a node with no observers to the current wave, but the Python engine's `notify()` returns before marking such a node. So if a signal was written inside a wave, a computed subscribed to it, and the signal was written again in the same wave, the Rust engine kept the stale value. A parity test now covers it (`test_signal_rewritten_in_one_wave_reaches_observers_added_between_writes`). With it, `tests/engine` has 69 tests: 69 passed on 3.14.3, on 3.14.3 under `-X dev`, and on 3.12.12. The full suite gives 476 passed.

Rerun of the benchmark on `e92454f`:

```
                             python       rust  speedup
    cached Computed read      135ns       57ns     2.4x
     write+read, chain 1     2052ns      682ns     3.0x
     write+read, chain 4     6662ns     1878ns     3.5x
    write+read, chain 16    24845ns     5913ns     4.2x
    write+read, chain 64   132329ns    21919ns     6.0x
          per extra node     2056ns      353ns
          500-leaf frame     2281us      525us     4.3x
```

Carried to Phase 2: a subclass whose `__init__` calls `super().__init__(value)` raises `TypeError`, because the native classes only define `__new__`. A no-op `__init__` in the facade would make this worse: it would silently drop a value the subclass transforms. Subclasses with extra constructor arguments also fail in `__new__`. The fix is a construction protocol (`__new__` accepts extra arguments, `__init__` stores the value). `_FieldSource` and `Binding` need that protocol anyway.

### Gate (Task 6)

| Criterion | Threshold | Result | |
| --- | --- | --- | --- |
| 1. Correctness | `tests/engine` passes on 3.14 (also `-X dev`) and 3.12 locally, and on 3.12–3.14 in CI | Local: 69 passed on all three. CI on `e92454f` (Linux): `test` gave 476 passed on 3.12, 3.13 and 3.14; `type checks` and `ruff` passed | pass |
| 2. Per-node cost | ≤ 0.40 µs | 0.353 µs on `e92454f` (0.336–0.343 µs in three runs on `d9335d6`) | pass |
| 3. Frame cost | ≤ 0.60 ms | 0.525 ms on `e92454f` (0.504–0.537 ms in three runs on `d9335d6`) | pass |
| 4. No crash | no crash or "dropped on another thread" error | None locally. The CI logs have no panic, unraisable-exception, "another thread" or segfault output | pass |

**Decision: proceed to Phase 2.** The frame margin is the thinnest: the slowest run, 0.537 ms, is about 10% under the 0.60 ms limit. Phase 5's tuning items (the dependency index and per-call allocations) target exactly that cost.
