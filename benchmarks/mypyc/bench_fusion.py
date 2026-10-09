"""Estimate per-node overhead and the ceiling on gains from fusing operator chains."""

import operator
import timeit

from signified import Computed, Signal


def best(fn, number=2000, repeat=7):
    return min(timeit.repeat(fn, number=number, repeat=repeat)) / number * 1e9


OPS = [(operator.add, 1.5), (operator.mul, 0.5), (operator.sub, 2.0), (operator.truediv, 3.0)]


def build_signified(s, depth):
    x = s
    for i in range(depth):
        op, k = OPS[i % len(OPS)]
        x = op(x, k)  # dunder -> Computed per op
    return x


def build_fused(s, depth):
    # What a closure-composing compiler would emit: one Computed, nested closures.
    f = lambda: s.value  # noqa: E731
    for i in range(depth):
        op, k = OPS[i % len(OPS)]
        f = (lambda g, op, k: lambda: op(g(), k))(f, op, k)
    return Computed(f)


def build_fused_codegen(s, depth):
    # What a source-generating compiler would emit: one flat expression.
    expr = "s.value"
    sym = {operator.add: "+", operator.mul: "*", operator.sub: "-", operator.truediv: "/"}
    for i in range(depth):
        op, k = OPS[i % len(OPS)]
        expr = f"({expr} {sym[op]} {k})"
    return Computed(eval(f"lambda: {expr}", {"s": s}))


def chain_step(builder, depth):
    s = Signal(1.0)
    out = builder(s, depth)
    out.value
    state = {"i": 0}

    def step():
        state["i"] += 1
        s.value = float(state["i"])
        return out.value

    return step


print(f"{'depth':>5} {'signified':>12} {'fused-closure':>14} {'fused-codegen':>14} {'per-node ovh':>13}")
for depth in (1, 4, 16, 64):
    r = {
        name: best(chain_step(b, depth))
        for name, b in (("signified", build_signified), ("closure", build_fused), ("codegen", build_fused_codegen))
    }
    per_node = (r["signified"] - r["codegen"]) / depth
    print(f"{depth:>5} {r['signified']:>10.0f}ns {r['closure']:>12.0f}ns {r['codegen']:>12.0f}ns {per_node:>11.0f}ns")


def frame_step(kind, n=500):
    params = [(i * 0.1, 1.0 + i % 3, float(i)) for i in range(n)]
    state = {"f": 0}
    if kind == "plain":

        def step():
            state["f"] += 1
            tv = float(state["f"])
            return [(tv - a) * b + c for a, b, c in params]

        return step
    t = Signal(0.0)
    if kind == "signified":
        leaves = [(t - a) * b + c for a, b, c in params]  # 3 Computeds per leaf
    else:
        leaves = [Computed(lambda a=a, b=b, c=c: (t.value - a) * b + c) for a, b, c in params]  # 1 per leaf
    for leaf in leaves:
        leaf.value

    def step():
        state["f"] += 1
        t.value = float(state["f"])
        return [leaf.value for leaf in leaves]

    return step


print()
print("frame workload: 1 clock -> 500 leaves of `(t - a) * b + c`")
for kind in ("signified", "fused", "plain"):
    print(f"  {kind:>10}: {best(frame_step(kind), number=50) / 1000:8.1f} us/frame")
