# Rust Core Spike Results

Plan: `notes/rust-core-spike-plan-2026-10-09.md` (Tasks 1–6).

- **Date:** 2026-10-09
- **Commits measured:** `d9335d6` (engine, Task 3) and `e92454f` (review fix) on `rust-core-spike`, branched from `main` at `9e1050a`
- **Machine:** Apple M1 Max (10 cores, 64 GB), macOS 26.2 (25C56), arm64
- **Python:** CPython 3.14.3 (uv-managed `.venv`); 3.12.12 for the 3.12 run
- **Toolchain:** rustc 1.93.0, PyO3 0.29.3 (`abi3-py312`), maturin release build via `uv sync`

## Benchmark

`uv run python benchmarks/spike_per_node.py`, exactly as printed:

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

## Tests (Task 3)

| Run | Command | Result |
| --- | --- | --- |
| CPython 3.14.3 | `uv run pytest tests/spike -o addopts="" -q -W error::pytest.PytestUnraisableExceptionWarning` | 67 passed |
| CPython 3.14.3, `-X dev` | `uv run python -X dev -m pytest tests/spike -o addopts="" -q` | 67 passed |
| CPython 3.12.12 | `.venv-3.12/bin/python -m pytest tests/spike -o addopts="" -q -W error::pytest.PytestUnraisableExceptionWarning` | 67 passed |
| Full suite, 3.14.3 | `uv run pytest -q` | 474 passed (407 existing + 67 spike) |

pyright: 0 errors. ruff check and format: clean. `cargo fmt --check` and `cargo clippy --release -- -D warnings`: clean.

## Review fix (`e92454f`)

The whole-branch review found one engine-parity bug. `notify` added a node with no observers to the current wave, but the Python engine's `notify()` returns before marking such a node. So if a signal was written inside a wave, a computed subscribed to it, and the signal was written again in the same wave, the Rust engine kept the stale value. A parity test now covers it (`test_signal_rewritten_in_one_wave_reaches_observers_added_between_writes`). With it, `tests/spike` has 69 tests: 69 passed on 3.14.3, on 3.14.3 under `-X dev`, and on 3.12.12. The full suite gives 476 passed.

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

## Gate (Task 6)

| Criterion | Threshold | Result | |
| --- | --- | --- | --- |
| 1. Correctness | `tests/spike` passes on 3.14 (also `-X dev`) and 3.12 locally, and on 3.12–3.14 in CI | Local: 69 passed on all three. CI on `e92454f` (Linux): `test` gave 476 passed on 3.12, 3.13 and 3.14; `type checks` and `ruff` passed | pass |
| 2. Per-node cost | ≤ 0.40 µs | 0.353 µs on `e92454f` (0.336–0.343 µs in three runs on `d9335d6`) | pass |
| 3. Frame cost | ≤ 0.60 ms | 0.525 ms on `e92454f` (0.504–0.537 ms in three runs on `d9335d6`) | pass |
| 4. No crash | no crash or "dropped on another thread" error | None locally. The CI logs have no panic, unraisable-exception, "another thread" or segfault output | pass |

**Decision: proceed to Phase 2.** The frame margin is the thinnest: the slowest run, 0.537 ms, is about 10% under the 0.60 ms limit. Phase 5's tuning items (the dependency index and per-call allocations) target exactly that cost.
