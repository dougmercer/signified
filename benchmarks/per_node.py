"""Per-node cost of the Python engine vs the Rust core (signified._native).

Usage: uv run python benchmarks/per_node.py
Reference numbers from the mypyc experiment (origin/mypyc-experiment,
notes/mypyc-2026-10-09.md): per extra node 0.70-0.87 us, 500-leaf frame 1.21 ms.
"""

import operator
import timeit

from signified import Computed as PyComputed
from signified import Signal as PySignal
from signified import _mixin, _native

OPS = [(operator.add, 1.5), (operator.mul, 0.5), (operator.sub, 2.0), (operator.truediv, 3.0)]
ENGINES = {
    "python": (PySignal, PyComputed, _mixin._computed_call),
    "rust": (_native.Signal, _native.Computed, _native.computed_call),
}


def best_ns(fn, number=2000, repeat=7):
    return min(timeit.repeat(fn, number=number, repeat=repeat)) / number * 1e9


def use(engine):
    signal_cls, computed_cls, computed_call = ENGINES[engine]
    _mixin._computed_call = computed_call  # operators build this engine's nodes
    return signal_cls, computed_cls


def chain_step(engine, depth):
    signal_cls, _ = use(engine)
    s = signal_cls(1.0)
    x = s
    for i in range(depth):
        op, k = OPS[i % len(OPS)]
        x = op(x, k)
    x.value
    state = {"i": 0}

    def step():
        state["i"] += 1
        s.value = float(state["i"])
        return x.value

    return step


def frame_step(engine, leaves=500):
    signal_cls, _ = use(engine)
    t = signal_cls(0.0)
    nodes = [(t - i * 0.1) * (1.0 + i % 3) + float(i) for i in range(leaves)]
    for node in nodes:
        node.value
    state = {"f": 0}

    def step():
        state["f"] += 1
        t.value = float(state["f"])
        return [node.value for node in nodes]

    return step


def cached_read(engine):
    signal_cls, computed_cls = use(engine)
    s = signal_cls(1)
    c = computed_cls(lambda: s.value + 1)
    c.value
    return lambda: c.value


try:
    print(f"{'':>24} {'python':>10} {'rust':>10} {'speedup':>8}")
    rows = [("cached Computed read", lambda e: cached_read(e), 200_000)]
    rows += [(f"write+read, chain {d}", lambda e, d=d: chain_step(e, d), 2000) for d in (1, 4, 16, 64)]
    for label, make, number in rows:
        py_ns, rs_ns = (best_ns(make(engine), number=number) for engine in ENGINES)
        print(f"{label:>24} {py_ns:>8.0f}ns {rs_ns:>8.0f}ns {py_ns / rs_ns:>7.1f}x")
    py_64, rs_64 = (best_ns(chain_step(e, 64)) for e in ENGINES)
    py_0, rs_0 = (best_ns(chain_step(e, 0)) for e in ENGINES)
    print(f"{'per extra node':>24} {(py_64 - py_0) / 64:>8.0f}ns {(rs_64 - rs_0) / 64:>8.0f}ns")
    py_frame, rs_frame = (best_ns(frame_step(e), number=50) / 1000 for e in ENGINES)
    print(f"{'500-leaf frame':>24} {py_frame:>8.0f}us {rs_frame:>8.0f}us {py_frame / rs_frame:>7.1f}x")
finally:
    _mixin._computed_call = ENGINES["python"][2]
