"""User code running inside the engine: notify callbacks, computes, deep graphs."""

import pytest

from signified import Computed, Signal, untracked


def test_observer_writes_other_signal_during_notify():
    a = Signal(1)
    b = Signal(10)
    total = Computed(lambda: a.value + b.value)
    assert total.value == 11

    class WritesB:
        def update(self) -> None:
            b.value = 20

    observer = WritesB()
    a.subscribe(observer)
    a.value = 2
    assert total.value == 22


def test_observer_writes_the_signal_it_observes():
    a = Signal(1)
    doubled = a * 2

    class BumpsOnce:
        fired = False

        def update(self) -> None:
            if not self.fired:
                self.fired = True
                a.value = a.value + 100

    observer = BumpsOnce()
    a.subscribe(observer)
    a.value = 2
    assert a.value == 102
    assert doubled.value == 204


def test_observer_reads_during_notify():
    a = Signal(1)
    doubled = a * 2
    seen = []

    class Reads:
        def update(self) -> None:
            seen.append(doubled.value)

    observer = Reads()
    a.subscribe(observer)
    a.value = 3
    assert seen == [6]


def test_compute_may_write_an_unrelated_signal():
    log = Signal(0)
    s = Signal(1)

    def compute():
        log.value = log.value + 1
        return s.value * 2

    c = Computed(compute)
    assert c.value == 2
    s.value = 3
    assert c.value == 6
    with untracked():
        assert log.value == 2


def test_failed_compute_keeps_dependencies_read_before_failure():
    gate = Signal(False)
    s = Signal(1)

    def compute():
        value = s.value
        if not gate.value:
            raise ValueError("closed")
        return value

    c = Computed(compute)
    with pytest.raises(ValueError):
        c.value
    gate.value = True
    assert c.value == 1


def test_moderate_chain_works():
    s = Signal(0)
    x = s
    for _ in range(100):
        x = x + 1
    assert x.value == 100
    s.value = 1
    assert x.value == 101


def test_very_deep_chain_raises_recursion_error_instead_of_crashing():
    s = Signal(0)
    x = s
    for _ in range(100_000):
        x = x + 1
    with pytest.raises(RecursionError):
        x.value


def test_observer_error_leaves_engine_usable():
    a = Signal(1)
    doubled = a * 2

    class FailsOnce:
        failed = False

        def update(self) -> None:
            if not self.failed:
                self.failed = True
                raise ValueError("observer failed")

    observer = FailsOnce()
    a.subscribe(observer)
    with pytest.raises(ValueError, match="observer failed"):
        a.value = 2
    assert doubled.value == 4
    a.value = 3  # a later wave notifies normally
    assert doubled.value == 6


def test_observer_subscribing_during_notify_is_kept():
    a = Signal(1)
    created = []

    class Spawns:
        def update(self) -> None:
            if not created:
                created.append(a + 100)
                created[0].value  # subscribes to `a` while `a` is notifying

    observer = Spawns()
    a.subscribe(observer)
    a.value = 2
    assert created[0].value == 102
    a.value = 3
    assert created[0].value == 103


def test_signal_rewritten_in_one_wave_reaches_observers_added_between_writes():
    a = Signal(1)
    b = Signal(0)
    seen = []

    class WritesBTwice:
        def update(self) -> None:
            b.value = 1  # b has no observers yet
            doubled = b * 2
            seen.append(doubled.value)  # subscribes `doubled` to `b`
            b.value = 2
            seen.append(doubled.value)

    observer = WritesBTwice()
    a.subscribe(observer)
    a.value = 2
    assert seen == [2, 4]


def test_deep_chain_on_a_worker_thread_raises_instead_of_crashing():
    import threading

    outcome = []

    def run():
        s = Signal(0)
        x = s
        for _ in range(100_000):
            x = x + 1
        try:
            x.value
        except RecursionError:
            outcome.append("recursion")
        else:
            outcome.append("value")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert outcome == ["recursion"]


def test_unmatched_pop_untracked_keeps_the_computation_tracking():
    from signified import _core

    s = Signal(1)
    errors = []

    def compute():
        try:
            _core.pop_untracked()
        except RuntimeError as error:
            errors.append(error)
        return s.value

    c = Computed(compute)
    assert c.value == 1
    assert len(errors) == 1
    s.value = 2
    assert c.value == 2


def test_observers_run_after_the_change_has_propagated():
    from signified import batch

    a = Signal(1)
    b = a * 2
    seen = []

    class Reads:
        def update(self) -> None:
            seen.append((a.value, b.value))

    observer = Reads()
    a.subscribe(observer)
    with batch():
        a.value = 2
        a.value = 3
        assert seen == []
    assert seen == [(3, 6)]


def test_signal_written_twice_during_propagation_keeps_dependents_current():
    a = Signal(0)
    b = Signal(0)
    c = b * 10
    assert c.value == 0
    seen = []

    class WritesTwice:
        def update(self) -> None:
            b.value = 1
            seen.append(c.value)
            b.value = 2
            seen.append(c.value)

    observer = WritesTwice()
    a.subscribe(observer)
    a.value = 1
    assert seen == [10, 20]
    assert c.value == 20


def test_observer_that_resubscribes_itself_still_hits_the_run_limit():
    source = Signal(0)

    class Resubscribes:
        runs = 0

        def update(self) -> None:
            self.runs += 1
            if self.runs >= 500:  # bound the loop if the limit is missed
                return
            source.unsubscribe(self)
            source.subscribe(self)
            source.value += 1

    observer = Resubscribes()
    source.subscribe(observer)
    with pytest.raises(RuntimeError, match="did not settle"):
        source.value = 1
    assert observer.runs == 100
