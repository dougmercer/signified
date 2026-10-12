"""signified on the graphs of the Rust comparison (src/main.rs), timed the same way.

Two kinds of nodes: Python functions (`computed(fn)(...)`), and native kernels created through the
C API by the example extension in rust/api-example (skipped if it is not installed).

Usage (from the repository root):
    uv sync --group test
    uv pip install --no-deps ./rust/api-example
    uv run --no-sync python benchmarks/rust_comparison/signified_graphs.py
    uv run --no-sync python benchmarks/rust_comparison/signified_graphs.py --node-kinds

Prints CSV like the Rust harness: library,workload,microseconds per operation (best of 5 samples).
`--node-kinds` instead compares the cost of a 1000-node chain update for several kinds of node.
"""

import argparse
import itertools
import math
import sys
import time

from signified import Computed, Signal, computed
from signified._core import _native_test_sum

try:
    import signified_api_example as example
except ImportError:
    example = None

sys.setrecursionlimit(1_000_000)  # the first read of a deep chain refreshes it recursively
N, W, D = 1000, 100, 10


def bench(lib, workload, op):
    iters = 1
    while True:
        start = time.perf_counter()
        for _ in range(iters):
            op()
        if time.perf_counter() - start > 0.02:
            break
        iters *= 2
    iters *= 5
    best = math.inf
    for _ in range(5):
        start = time.perf_counter()
        for _ in range(iters):
            op()
        best = min(best, (time.perf_counter() - start) / iters)
    print(f"{lib},{workload},{best * 1e6:.3f}", flush=True)


def python_nodes():
    return dict(
        zero_value=0,
        inc=lambda node: computed(lambda x: x + 1)(node),
        leaf=lambda src, i: computed(lambda x, i=i: x + i)(src),
        add=lambda a, b: computed(lambda a, b: a + b)(a, b),
        total=lambda nodes: computed(lambda *xs: sum(xs))(*nodes),
        zero=lambda src: computed(lambda x: x * 0)(src),
    )


def native_nodes(ex):
    return dict(
        zero_value=0.0,
        inc=lambda node: ex.weighted_sum([1.0, 1.0], node, 1.0),
        leaf=lambda src, i: ex.weighted_sum([1.0, 1.0], src, float(i)),
        add=lambda a, b: ex.weighted_sum([1.0, 1.0], a, b),
        total=lambda nodes: ex.weighted_sum([1.0] * len(nodes), *nodes),
        zero=lambda src: ex.weighted_sum([0.0], src),
    )


def chain_on(nodes, base):
    node = base
    for _ in range(N - 1):
        node = nodes["inc"](node)
    return node


def updates(lib, workload, src, out, expected):
    src.value = 7
    assert out.value == expected(7), (lib, workload, out.value, expected(7))
    counter = itertools.count(8)

    def op():
        src.value = next(counter)
        out.value

    bench(lib, workload, op)


def run_workloads(lib, nodes):
    number = type(nodes["zero_value"])

    src = Signal(nodes["zero_value"])
    updates(lib, "chain", src, chain_on(nodes, nodes["inc"](src)), lambda v: v + N)

    src = Signal(nodes["zero_value"])
    out = nodes["total"]([nodes["leaf"](src, i) for i in range(N)])
    updates(lib, "fan", src, out, lambda v: N * v + N * (N - 1) // 2)

    src = Signal(nodes["zero_value"])
    layer = [nodes["leaf"](src, j) for j in range(W)]
    for _ in range(D - 1):
        layer = [nodes["add"](layer[j], layer[(j + 1) % W]) for j in range(W)]
    out = nodes["total"](layer)
    updates(lib, "layers", src, out, lambda v: 2 ** (D - 1) * (W * v + W * (W - 1) // 2))

    src = Signal(nodes["zero_value"])
    out = chain_on(nodes, nodes["inc"](nodes["zero"](src)))
    updates(lib, "cutoff", src, out, lambda _: N)

    def create():
        chain_on(nodes, nodes["inc"](Signal(number(1)))).value

    bench(lib, "create", create)


def node_kinds():
    kinds = [
        ("Python function (computed)", lambda node: computed(lambda x: x + 1.0)(node)),
        ("identity Python function", lambda node: computed(lambda x: x)(node)),
        ("engine test kernel (C API)", lambda node: _native_test_sum(Computed, node, 1.0)),
    ]
    if example is not None:
        ex = example
        kinds.append(("example kernel (C API)", lambda node: ex.weighted_sum([1.0, 1.0], node, 1.0)))
    for name, make in kinds:
        src = Signal(0.0)
        out = make(src)
        for _ in range(N - 1):
            out = make(out)
        counter = itertools.count(1)
        best = math.inf
        for _ in range(5):
            start = time.perf_counter()
            for _ in range(200):
                src.value = float(next(counter))
                out.value
            best = min(best, (time.perf_counter() - start) / 200)
        print(f"{name:30s} {best * 1e6:7.1f} us per update of a {N}-node chain", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--node-kinds", action="store_true", help="compare kinds of node on a chain")
    args = parser.parse_args()
    if args.node_kinds:
        node_kinds()
        return
    run_workloads("signified (Python functions)", python_nodes())
    if example is None:
        print("# signified_api_example is not installed: skipping native kernels", file=sys.stderr)
    else:
        run_workloads("signified (native kernels)", native_nodes(example))


if __name__ == "__main__":
    main()
