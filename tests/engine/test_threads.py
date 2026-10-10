"""Threads: each thread tracks, batches and runs effects on its own."""

import sys
import threading

import pytest

from signified import Computed, Effect, Signal, _core, batch

pytestmark = pytest.mark.skipif(sys.platform == "emscripten", reason="Pyodide has no threads")


def run_on_thread(fn):
    thread = threading.Thread(target=fn)
    thread.start()
    thread.join()


def test_reads_on_another_thread_do_not_join_a_running_computation():
    a, b = Signal(1), Signal(2)
    started, release = threading.Event(), threading.Event()
    runs = []

    def compute():
        runs.append(1)
        started.set()
        release.wait()
        return a.value

    c = Computed(compute)
    worker = threading.Thread(target=lambda: c.value)
    worker.start()
    started.wait()
    b.value  # read here while c computes on the worker
    release.set()
    worker.join()

    b.value = 3
    assert c.value == 1
    assert len(runs) == 1


def test_open_batch_on_another_thread_does_not_hold_back_effects_here():
    s = Signal(0)
    seen = []
    effect = Effect(lambda: seen.append(s.value))
    entered, release = threading.Event(), threading.Event()

    def hold_batch():
        with batch():
            entered.set()
            release.wait()

    worker = threading.Thread(target=hold_batch)
    worker.start()
    entered.wait()
    try:
        s.value = 1
        assert seen == [0, 1]
    finally:
        release.set()
        worker.join()
    effect.dispose()


def test_thread_that_exits_inside_a_batch_does_not_hold_back_effects_here():
    worker_seen = []
    box = {}

    def leave_batch_open():
        box["s"] = Signal(0)
        box["effect"] = Effect(lambda: worker_seen.append(box["s"].value))
        batch().__enter__()
        box["s"].value = 1  # queued on this thread, which then exits

    run_on_thread(leave_batch_open)

    s = Signal(0)
    seen = []
    effect = Effect(lambda: seen.append(s.value))
    s.value = 1
    assert seen == [0, 1]
    assert worker_seen == [0]
    effect.dispose()
    box["effect"].dispose()


def test_reading_a_computed_while_another_thread_computes_it_says_so():
    started, release = threading.Event(), threading.Event()

    def compute():
        started.set()
        release.wait()
        return 1

    c = Computed(compute)
    worker = threading.Thread(target=lambda: c.value)
    worker.start()
    started.wait()
    try:
        with pytest.raises(RuntimeError, match="another thread"):
            c.value
    finally:
        release.set()
        worker.join()
    assert c.value == 1


def test_separate_graphs_on_separate_threads_stay_correct():
    errors = []
    finals = {}

    def run(offset):
        try:
            s = Signal(0)

            def plus_offset():
                total = 0
                for _ in range(20):  # gives the interpreter places to switch threads
                    total += 1
                return s.value + offset + total - 20

            c = Computed(plus_offset)
            seen = []
            effect = Effect(lambda: seen.append(c.value))
            for i in range(1, 201):
                s.value = i
            finals[offset] = (c.value, seen[-1], len(c._deps))
            effect.dispose()
        except Exception as error:
            errors.append(error)

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=run, args=(offset,)) for offset in (1000, 2000, 3000, 4000)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(interval)

    assert errors == []
    assert finals == {
        1000: (1200, 1200, 1),
        2000: (2200, 2200, 1),
        3000: (3200, 3200, 1),
        4000: (4200, 4200, 1),
    }


def test_graph_moved_between_fresh_threads_sees_new_writes():
    box = {}

    def build():
        box["s"] = Signal(1)
        box["c"] = box["s"] * 2
        box["c"].value

    def write_and_read():
        box["s"].value = 5
        box["read"] = box["c"].value

    run_on_thread(build)
    run_on_thread(write_and_read)
    assert box["read"] == 10


def test_plugin_hooks_apply_on_every_thread(monkeypatch):
    class Recorder:
        def __init__(self) -> None:
            self.updated_values = []

        def updated(self, *, value) -> None:
            self.updated_values.append(value)

    hook = Recorder()
    monkeypatch.setattr(_core.config, "hooks", hook)
    box = {}

    def write():
        box["s"] = Signal(0)
        box["s"].value = 1

    run_on_thread(write)
    assert hook.updated_values == [box["s"]]
