"""Per-node cost of signified's reactive graph.

Usage:
    uv run python benchmarks/per_node.py
    uv run python benchmarks/per_node.py --compare /path/to/other/venv/bin/python

`--compare` runs the same workloads under another interpreter (for example a
virtualenv with signified from `main`) and prints both columns.
"""

import argparse
import json
import operator
import subprocess
import sys
import timeit

from signified import Computed, Signal

OPS = [(operator.add, 1.5), (operator.mul, 0.5), (operator.sub, 2.0), (operator.truediv, 3.0)]


def best_ns(fn, number=2000, repeat=7):
    return min(timeit.repeat(fn, number=number, repeat=repeat)) / number * 1e9


def chain_step(depth):
    s = Signal(1.0)
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


def frame_step(leaves=500):
    t = Signal(0.0)
    nodes = [(t - i * 0.1) * (1.0 + i % 3) + float(i) for i in range(leaves)]
    for node in nodes:
        node.value
    state = {"f": 0}

    def step():
        state["f"] += 1
        t.value = float(state["f"])
        return [node.value for node in nodes]

    return step


def cached_read():
    s = Signal(1)
    c = Computed(lambda: s.value + 1)
    c.value
    return lambda: c.value


def build_chain(depth=64):
    def build():
        s = Signal(1.0)
        x = s
        for i in range(depth):
            op, k = OPS[i % len(OPS)]
            x = op(x, k)
        return x.value

    return build


def measure():
    rows = {"cached Computed read": best_ns(cached_read(), number=200_000)}
    for depth in (1, 4, 16, 64):
        rows[f"write+read, chain {depth}"] = best_ns(chain_step(depth))
    rows["per extra node"] = (best_ns(chain_step(64)) - best_ns(chain_step(0))) / 64
    rows["build+read, chain 64"] = best_ns(build_chain(), number=200)
    rows["500-leaf frame"] = best_ns(frame_step(), number=50)
    return rows


def fmt(ns):
    return f"{ns / 1000:.1f}us" if ns >= 10_000 else f"{ns:.0f}ns"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print raw nanoseconds as JSON")
    parser.add_argument("--compare", metavar="PYTHON", help="also run under this interpreter and compare")
    args = parser.parse_args()

    rows = measure()
    if args.json:
        print(json.dumps(rows))
        return
    if not args.compare:
        for label, ns in rows.items():
            print(f"{label:>24} {fmt(ns):>10}")
        return
    output = subprocess.run([args.compare, __file__, "--json"], check=True, capture_output=True, text=True).stdout
    other = json.loads(output)
    print(f"{'':>24} {'other':>10} {'this':>10} {'speedup':>8}")
    for label, ns in rows.items():
        print(f"{label:>24} {fmt(other[label]):>10} {fmt(ns):>10} {other[label] / ns:>7.1f}x")


if __name__ == "__main__":
    sys.exit(main())
