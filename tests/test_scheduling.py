"""Observable scheduling, tracking, failure, and lifetime contracts."""

import gc
import weakref

import pytest

from signified import Computed, Effect, Signal, batch, deep_unref, untracked


def test_batch_immediate_writes_fresh_reads_and_nested_coalescing():
    a, b = Signal(1), Signal(2)
    total = Computed(lambda: a.value + b.value)
    seen = []
    watcher = Effect(lambda: seen.append(total.value))
    with batch():
        a.value = 10
        assert total.value == 12
        with batch():
            b.value = 20
            assert total.value == 30
        assert seen == [3]
    assert seen == [3, 30]
    watcher.dispose()


def test_diamond_is_current_before_effect_runs_without_explicit_batch():
    source = Signal(1)
    left = Computed(lambda: source.value * 2)
    right = Computed(lambda: source.value * 3)
    seen = []
    watcher = Effect(lambda: seen.append((source.value, left.value, right.value)))
    source.value = 2
    assert seen == [(1, 2, 3), (2, 4, 6)]
    watcher.dispose()


def test_batch_initial_effect_deferred_and_disposed_effect_skipped():
    source = Signal(0)
    seen = []
    with batch():
        first = Effect(lambda: seen.append(source.value))
        second = Effect(lambda: seen.append("disposed"))
        second.dispose()
        second.dispose()
        source.value = 2
        assert not seen
    assert seen == [2]
    first.dispose()


def test_cascading_writes_requeue_an_already_run_effect():
    a, b = Signal(0), Signal(0)
    seen = []
    observer = Effect(lambda: seen.append(a.value))
    writer = Effect(lambda: setattr(a, "value", b.value))
    with batch():
        a.value = 1
        b.value = 2
    assert seen == [0, 1, 2]
    observer.dispose()
    writer.dispose()


def test_self_write_on_first_run_settles_without_recursive_execution():
    source = Signal(0)
    seen = []

    def advance():
        value = source.value
        seen.append(value)
        if value < 3:
            source.value = value + 1

    watcher = Effect(advance)
    assert seen == [0, 1, 2, 3]
    watcher.dispose()


def test_failed_effect_retries_and_healthy_effects_continue():
    source = Signal(1)
    seen, healthy = [], []

    def body():
        value = source.value
        seen.append(value)
        if value == 2:
            raise ValueError("boom")

    watcher = Effect(body)
    other = Effect(lambda: healthy.append(source.value))
    with pytest.raises(ValueError, match="boom"):
        source.value = 2
    source.value = 3
    assert seen == healthy == [1, 2, 3]
    watcher.dispose()
    other.dispose()


def test_failed_intermediate_computed_does_not_block_future_notifications():
    source = Signal(1)

    def compute():
        value = source.value
        if value == 2:
            raise ValueError("computed failed")
        return value * 2

    intermediate = Computed(compute)
    tail = Computed(lambda: intermediate.value + 1)
    seen = []
    watcher = Effect(lambda: seen.append(tail.value))
    with pytest.raises(ValueError):
        source.value = 2
    source.value = 3
    assert seen == [3, 7]
    watcher.dispose()


def test_failed_branch_restores_previous_dependencies():
    flag, left, right = Signal(True), Signal(1), Signal(2)
    calls = []

    def body():
        value = left.value if flag.value else right.value
        calls.append(value)
        if not flag.value:
            raise ValueError("right")

    watcher = Effect(body)
    with pytest.raises(ValueError):
        flag.value = False
    right.value = 3  # failed-run-only dependency is not retained
    assert calls == [1, 2]
    with pytest.raises(ValueError):
        left.value = 4
    flag.value = True
    assert calls == [1, 2, 3, 4]
    watcher.dispose()


def test_dispose_during_callback_does_not_resubscribe():
    source = Signal(0)
    seen = []

    def body():
        value = source.value
        seen.append(value)
        if value:
            watcher.dispose()
            source.value = 2
            _ = source.value

    watcher = Effect(body)
    source.value = 1
    source.value = 3
    assert seen == [0, 1]
    assert not source._observers


def test_queue_does_not_keep_effect_alive():
    source = Signal(0)
    seen = []
    watcher = Effect(lambda: seen.append(source.value))
    reference = weakref.ref(watcher)
    with batch():
        source.value = 1
        del watcher
        gc.collect()
        assert reference() is None
    assert seen == [0]


def test_run_counts_do_not_keep_previously_run_effect_alive():
    source, trigger = Signal(0), Signal(0)
    seen = []
    owners = []

    def body():
        seen.append(source.value)
        if source.value:
            owners.clear()

    owners.append(Effect(body))
    reference = weakref.ref(owners[0])
    writer = Effect(lambda: setattr(source, "value", trigger.value))
    with batch():
        source.value = 1
        trigger.value = 2
    gc.collect()
    assert reference() is None
    assert seen == [0, 1]
    writer.dispose()


def test_batch_failure_is_always_group_and_scheduler_recovers():
    source = Signal(0)

    def fail():
        if source.value == 1:
            raise ValueError("effect")

    watcher = Effect(fail)
    with pytest.raises(ExceptionGroup) as caught:
        with batch():
            source.value = 1
    assert len(caught.value.exceptions) == 1
    assert isinstance(caught.value.exceptions[0], ValueError)
    source.value = 2
    watcher.dispose()


def test_batch_body_failure_flushes_applied_writes_and_is_unchanged():
    source = Signal(0)
    seen = []
    watcher = Effect(lambda: seen.append(source.value))
    error = LookupError("body")
    with pytest.raises(LookupError) as caught:
        with batch():
            source.value = 1
            raise error
    assert caught.value is error
    assert seen == [0, 1]
    watcher.dispose()


def test_body_and_multiple_effect_errors_are_all_preserved():
    source = Signal(0)

    def fail(error):
        if source.value:
            raise error

    one = Effect(lambda: fail(ValueError("one")))
    two = Effect(lambda: fail(TypeError("two")))
    body = LookupError("body")
    with pytest.raises(ExceptionGroup) as caught:
        with batch():
            source.value = 1
            raise body
    assert caught.value.exceptions[0] is body
    flush = caught.value.exceptions[1]
    assert isinstance(flush, ExceptionGroup)
    assert {type(e) for e in flush.exceptions} == {ValueError, TypeError}
    one.dispose()
    two.dispose()


def test_control_flow_abort_leaves_effects_eligible_for_future_updates():
    source = Signal(0)
    seen = []

    def stop():
        if source.value == 1:
            raise KeyboardInterrupt()

    one = Effect(stop)
    two = Effect(lambda: seen.append(source.value))
    with pytest.raises(KeyboardInterrupt):
        with batch():
            source.value = 1
    source.value = 2
    assert seen == [0, 2]
    one.dispose()
    two.dispose()


def test_nonsettling_feedback_is_bounded_and_scheduler_recovers():
    source, enabled = Signal(0), Signal(False)

    def increment():
        if enabled.value:
            source.value = source.value + 1

    watcher = Effect(increment)
    with pytest.raises(ExceptionGroup, match="effect failures") as caught:
        with batch():
            enabled.value = True
    assert any("did not settle" in str(e) for e in caught.value.exceptions)
    enabled.value = False
    watcher.dispose()
    seen = []
    healthy = Effect(lambda: seen.append(source.value))
    source.value = 200
    assert seen[-1] == 200
    healthy.dispose()


def test_untracked_nested_computed_keeps_its_own_dependencies():
    source, trigger = Signal(1), Signal(0)
    inner = Computed(lambda: source.value * 2)
    seen = []

    def body():
        _ = trigger.value
        with untracked():
            with untracked():
                seen.append(inner.value)

    watcher = Effect(body)
    source.value = 2
    assert inner.value == 4
    assert seen == [2]
    trigger.value = 1
    assert seen == [2, 4]
    watcher.dispose()


def test_untracked_restores_tracking_after_exception_and_deep_resolution():
    source, tracked = Signal(1), Signal(0)
    seen = []

    def body():
        try:
            with untracked():
                assert deep_unref({"x": source}) == {"x": source.value}
                raise ValueError()
        except ValueError:
            pass
        seen.append(tracked.value)

    watcher = Effect(body)
    source.value = 2
    tracked.value = 1
    assert seen == [0, 1]
    watcher.dispose()


def test_first_run_mutating_a_computed_dependency_retries_in_the_callback():
    source = Signal(0)
    derived = Computed(lambda: source.value * 2)
    calls = []

    def body():
        calls.append(derived.value)
        if not source.value:
            source.value = 1

    watcher = Effect(body)
    assert calls == [0, 2]
    watcher.dispose()


def test_failed_deferred_initial_run_has_no_automatic_retry_subscription():
    source = Signal(0)
    calls = []

    def body():
        calls.append(source.value)
        raise ValueError("initial")

    with pytest.raises(ExceptionGroup):
        with batch():
            watcher = Effect(body)
    source.value = 1
    assert calls == [0]
    assert not source._observers
    watcher.dispose()


def test_reentrant_batch_from_effect_joins_active_flush():
    source, target = Signal(0), Signal(0)
    seen = []

    def body():
        value = source.value
        with batch():
            target.value = value
            target.value = value * 2

    writer = Effect(body)
    observer = Effect(lambda: seen.append(target.value))
    source.value = 2
    assert seen == [0, 4]
    writer.dispose()
    observer.dispose()


def test_untracked_reads_keep_plugin_hooks(monkeypatch):
    from types import SimpleNamespace

    import signified._reactive as reactive
    from signified import unref

    source = Signal(1)
    reads = []
    hook = SimpleNamespace(read=lambda *, value: reads.append(id(value)))
    monkeypatch.setattr(reactive, "HOOKS_ENABLED", True)
    monkeypatch.setattr(reactive, "plugin_manager", SimpleNamespace(hook=hook))
    with untracked():
        assert source.value == 1
        assert unref(source) == 1
        assert deep_unref([source]) == [1]
    assert reads == [id(source)] * 3
