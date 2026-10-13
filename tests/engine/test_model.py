"""Random graphs and random writes, checked against recomputing from scratch.

Computeds read signals and earlier computeds, some through a branch (so
their dependencies change) and some through a sign (so changes often stop
there). After every step, each value read must match a direct evaluation,
a repeated read must evaluate nothing, and an effect watching one computed
must have run exactly when that computed's value changed.
"""

import random

import pytest

from signified import Computed, Effect, Signal, batch


def evaluate(formula, value):
    kind, inputs = formula
    if kind == "sum":
        return sum(value(i) for i in inputs)
    if kind == "pick":
        a, b, c, d = inputs
        return value(c) if value(a) > value(b) else value(d)
    (x,) = inputs
    v = value(x)
    return (v > 0) - (v < 0)


def random_formula(rng, index):
    kind = rng.choice(("sum", "pick", "sign"))
    if kind == "sum":
        return kind, [rng.randrange(index) for _ in range(rng.randint(1, 3))]
    if kind == "pick":
        return kind, [rng.randrange(index) for _ in range(4)]
    return kind, [rng.randrange(index)]


def run(seed):
    rng = random.Random(seed)
    signals = rng.randint(2, 7)
    computeds = rng.randint(1, 40)
    values = [rng.randint(-2, 2) for _ in range(signals)]
    sources = [Signal(v) for v in values]
    nodes: list[Signal[int] | Computed[int]] = list(sources)
    formulas = []
    evaluations = [0]

    for index in range(signals, signals + computeds):
        formula = random_formula(rng, index)
        formulas.append(formula)

        def compute(formula=formula):
            evaluations[0] += 1
            return evaluate(formula, lambda i: nodes[i].value)

        nodes.append(Computed(compute))

    def model():
        everything = list(values)
        for formula in formulas:
            everything.append(evaluate(formula, everything.__getitem__))
        return everything

    watched = signals + rng.randrange(computeds)
    seen = []
    effect = Effect(lambda: seen.append(nodes[watched].value))

    def write():
        signal = rng.randrange(signals)
        values[signal] = rng.randint(-2, 2)
        sources[signal].value = values[signal]

    for step in range(200):
        action = rng.randrange(4)
        if action < 2:
            write()
        elif action == 2:
            with batch():
                for _ in range(3):
                    write()
        else:
            expected = model()
            index = rng.randrange(len(nodes))
            assert nodes[index].value == expected[index], f"seed {seed}, step {step}, node {index}"
            before = evaluations[0]
            assert nodes[index].value == expected[index]
            assert evaluations[0] == before, f"seed {seed}, step {step}: a repeat read evaluated"
        assert seen[-1] == model()[watched], f"seed {seed}, step {step}: the effect is stale"
        assert all(a != b for a, b in zip(seen, seen[1:])), f"seed {seed}: the effect ran without a change: {seen}"

    expected = model()
    for index, node in enumerate(nodes):
        assert node.value == expected[index], f"seed {seed}, node {index} at the end"
    effect.dispose()


@pytest.mark.parametrize("block", range(10))
def test_random_graphs_match_recomputing_from_scratch(block):
    for seed in range(block * 50, (block + 1) * 50):
        run(seed)
