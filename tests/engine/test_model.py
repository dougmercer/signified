"""Random graphs and random writes, checked against recomputing from scratch.

Computeds read signals and earlier computeds, some through a branch (so
their dependencies change) and some through a sign (so changes often stop
there). After every step, each value read must match a direct evaluation,
a repeated read must evaluate nothing, an effect watching one computed
must have run exactly when that computed's value changed, and a `Watcher` of
some nodes must report each node whose value changed since it last asked.
Without samples, reads inside `Signal.at()` or batches (which may write a
signal and write it back), a node is calculated for one state of the signals
per step, so the watcher reports exactly those nodes.

With samples, some nodes are `sample(node, signal, at)` with a plain or
reactive `at`, which later nodes may read, and some reads happen inside
`Signal.at()` blocks.
"""

import random

import pytest

from signified import Computed, Effect, Signal, Watcher, batch, sample


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


def run(seed, samples=False):
    rng = random.Random(seed)
    signals = rng.randint(2, 7)
    computeds = rng.randint(1, 40)
    values = [rng.randint(-2, 2) for _ in range(signals)]
    sources = [Signal(v) for v in values]
    nodes: list[Signal[int] | Computed[int]] = list(sources)
    formulas = []
    evaluations = [0]

    for index in range(signals, signals + computeds):
        if samples and rng.random() < 0.2:
            # A sample of an earlier node, at a plain value or at an earlier node's value.
            node, signal = rng.randrange(index), rng.randrange(signals)
            at = ("plain", rng.randint(-2, 2)) if rng.random() < 0.5 else ("node", rng.randrange(index))
            formulas.append(("sample", (node, signal, at)))
            at_value = at[1] if at[0] == "plain" else nodes[at[1]]
            nodes.append(sample(nodes[node], sources[signal], at_value))
            continue
        formula = random_formula(rng, index)
        formulas.append(formula)

        def compute(formula=formula):
            evaluations[0] += 1
            return evaluate(formula, lambda i: nodes[i].value)

        nodes.append(Computed(compute))

    def model_of(world, upto):
        """Every node's value up to `upto` when the signals hold `world`."""
        everything = list(world)
        for formula in formulas[: max(0, upto + 1 - signals)]:
            if formula[0] == "sample":
                node, signal, (kind, at) = formula[1]
                substituted = list(world)
                substituted[signal] = at if kind == "plain" else everything[at]
                everything.append(model_of(substituted, node)[node])
            else:
                everything.append(evaluate(formula, everything.__getitem__))
        return everything

    def model():
        return model_of(values, len(nodes) - 1)

    watched = signals + rng.randrange(computeds)
    seen = []
    effect = Effect(lambda: seen.append(nodes[watched].value))
    watcher = Watcher()
    reported = {}
    for index in rng.sample(range(len(nodes)), min(6, len(nodes))):
        watcher.watch(nodes[index], index)
        reported[index] = model()[index]

    def write():
        signal = rng.randrange(signals)
        values[signal] = rng.randint(-2, 2)
        sources[signal].value = values[signal]

    for step in range(200):
        action = rng.randrange(5 if samples else 4)
        if action < 2:
            write()
        elif action == 2:
            with batch():
                for _ in range(3):
                    write()
        elif action == 4:
            # A read inside `Signal.at()`, which writes at the top level.
            signal = rng.randrange(signals)
            held = rng.randint(-2, 2)
            world = list(values)
            world[signal] = held
            index = rng.randrange(len(nodes))
            with sources[signal].at(held):
                got = nodes[index].value
            assert got == model_of(world, index)[index], f"seed {seed}, step {step}, node {index} inside at()"
        else:
            expected = model()
            index = rng.randrange(len(nodes))
            assert nodes[index].value == expected[index], f"seed {seed}, step {step}, node {index}"
            before = evaluations[0]
            assert nodes[index].value == expected[index]
            assert evaluations[0] == before, f"seed {seed}, step {step}: a repeat read evaluated"
        assert seen[-1] == model()[watched], f"seed {seed}, step {step}: the effect is stale"
        assert all(a != b for a, b in zip(seen, seen[1:])), f"seed {seed}: the effect ran without a change: {seen}"
        current = model()
        keys = watcher.changed()
        moved = {index for index, value in reported.items() if current[index] != value}
        assert len(keys) == len(set(keys)), f"seed {seed}, step {step}: a key was reported twice: {keys}"
        assert moved <= set(keys), f"seed {seed}, step {step}: changes not reported: {moved - set(keys)}"
        if not samples and action != 2:
            assert set(keys) == moved, f"seed {seed}, step {step}: reported without a change: {set(keys) - moved}"
        reported = {index: current[index] for index in reported}

    expected = model()
    for index, node in enumerate(nodes):
        assert node.value == expected[index], f"seed {seed}, node {index} at the end"
    effect.dispose()


@pytest.mark.parametrize("block", range(10))
def test_random_graphs_match_recomputing_from_scratch(block):
    for seed in range(block * 50, (block + 1) * 50):
        run(seed)


@pytest.mark.parametrize("block", range(10))
def test_random_graphs_with_samples_match_recomputing_from_scratch(block):
    for seed in range(block * 50, (block + 1) * 50):
        run(seed, samples=True)
