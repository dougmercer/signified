"""Randomized churn: dynamic dependencies, subscriptions, and freed consumers.

Exercises the observer-list bookkeeping (vacant slots, compaction, link
positions) against values and dependency counts computed directly.
"""

import gc
import random

from signified import Computed, Effect, Signal


def test_random_dependency_churn_keeps_values_and_observers_consistent():
    rng = random.Random(1234)
    values = [Signal(i) for i in range(40)]
    selectors = [Signal(tuple(rng.sample(range(40), rng.randint(0, 12)))) for _ in range(120)]

    def make(k):
        selector = selectors[k]
        return Computed(lambda: sum(values[i].value for i in selector.value))

    computeds = [make(k) for k in range(120)]
    runs = []
    effects = [Effect(lambda k=k: runs.append(computeds[k].value)) for k in range(0, 120, 7)]

    class Observer:
        def __init__(self):
            self.calls = 0

        def update(self):
            self.calls += 1

    observers = [Observer() for _ in range(30)]
    subscribed = set()

    for _ in range(600):
        action = rng.random()
        if action < 0.35:
            values[rng.randrange(40)].value = rng.randint(-50, 50)
        elif action < 0.65:
            k = rng.randrange(120)
            selectors[k].value = tuple(rng.sample(range(40), rng.randint(0, 12)))
        elif action < 0.75:
            k = rng.randrange(120)
            computeds[k] = make(k)  # the old computed is freed
            gc.collect()
        else:
            o, v = rng.randrange(30), rng.randrange(40)
            if (o, v) in subscribed:
                values[v].unsubscribe(observers[o])
                subscribed.discard((o, v))
            else:
                values[v].subscribe(observers[o])
                subscribed.add((o, v))
        if rng.random() < 0.3:
            for k in rng.sample(range(120), 20):
                expected = sum(values[i].value for i in selectors[k].value)
                assert computeds[k].value == expected

    for k in range(120):
        assert computeds[k].value == sum(values[i].value for i in selectors[k].value)
        assert set(computeds[k]._deps) == {selectors[k], *(values[i] for i in selectors[k].value)}

    # Each value's observers: the computeds that read it, plus subscriptions.
    for v in range(40):
        readers = sum(1 for k in range(120) if v in selectors[k].value)
        subscriptions = sum(1 for o, value in subscribed if value == v)
        assert values[v]._observer_count() == readers + subscriptions

    for effect in effects:
        effect.dispose()
