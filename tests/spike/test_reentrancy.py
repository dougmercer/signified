"""User code running inside the engine: notify callbacks, computes, deep graphs."""

import pytest


def test_observer_writes_other_signal_during_notify(rx):
    a = rx.Signal(1)
    b = rx.Signal(10)
    total = rx.Computed(lambda: a.value + b.value)
    assert total.value == 11

    class WritesB:
        def update(self) -> None:
            b.value = 20

    observer = WritesB()
    a.subscribe(observer)
    a.value = 2
    assert total.value == 22


def test_observer_writes_the_signal_it_observes(rx):
    a = rx.Signal(1)
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


def test_observer_reads_during_notify(rx):
    a = rx.Signal(1)
    doubled = a * 2
    seen = []

    class Reads:
        def update(self) -> None:
            seen.append(doubled.value)

    observer = Reads()
    a.subscribe(observer)
    a.value = 3
    assert seen == [6]


def test_compute_may_write_an_unrelated_signal(rx):
    log = rx.Signal(0)
    s = rx.Signal(1)

    def compute():
        log.value = log.value + 1
        return s.value * 2

    c = rx.Computed(compute)
    assert c.value == 2
    s.value = 3
    assert c.value == 6
    with rx.untracked():
        assert log.value == 2


def test_failed_compute_keeps_dependencies_read_before_failure(rx):
    gate = rx.Signal(False)
    s = rx.Signal(1)

    def compute():
        value = s.value
        if not gate.value:
            raise ValueError("closed")
        return value

    c = rx.Computed(compute)
    with pytest.raises(ValueError):
        c.value
    gate.value = True
    assert c.value == 1


def test_moderate_chain_works(rx):
    s = rx.Signal(0)
    x = s
    for _ in range(100):
        x = x + 1
    assert x.value == 100
    s.value = 1
    assert x.value == 101


def test_very_deep_chain_raises_recursion_error_instead_of_crashing(rx):
    s = rx.Signal(0)
    x = s
    for _ in range(100_000):
        x = x + 1
    with pytest.raises(RecursionError):
        x.value


def test_observer_error_leaves_engine_usable(rx):
    a = rx.Signal(1)
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


def test_observer_subscribing_during_notify_is_kept(rx):
    a = rx.Signal(1)
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


def test_signal_rewritten_in_one_wave_reaches_observers_added_between_writes(rx):
    a = rx.Signal(1)
    b = rx.Signal(0)
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


def test_deep_chain_on_a_worker_thread_raises_instead_of_crashing(rx):
    import threading

    outcome = []

    def run():
        s = rx.Signal(0)
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
