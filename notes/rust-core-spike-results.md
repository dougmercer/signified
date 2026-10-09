# Rust Core Spike Results

Plan: `notes/rust-core-spike-plan-2026-10-09.md` (Tasks 1–6).

- **Date:** 2026-10-09
- **Commit measured:** `d9335d6` (engine, Task 3) on `rust-core-spike`, branched from `main` at `9e1050a`
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

## Gate (Task 6)

Pending: CI on Linux for 3.12–3.14 (Task 5) hasn't run yet.
