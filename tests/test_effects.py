import pytest

from signified import Signal, effect


def test_effect_basic():
    x = Signal(0)
    calls = []

    @effect
    def track_value(x: int):
        calls.append(x)

    track_value(x)
    assert calls == [0]

    x.value = 1
    assert calls == [0, 1]

    x.value = 2
    assert calls == [0, 1, 2]


def test_effect_with_cleanup():
    x = Signal(0)
    calls = []
    cleanups = []

    @effect
    def track_with_cleanup(x: int):
        calls.append(x)

        def cleanup():
            cleanups.append(f"cleanup {x}")

        return cleanup

    e = track_with_cleanup(x)
    assert calls == [0]
    assert cleanups == []

    x.value = 1
    assert calls == [0, 1]
    assert cleanups == ["cleanup 0"]

    x.value = 2
    assert calls == [0, 1, 2]
    assert cleanups == ["cleanup 0", "cleanup 1"]

    e.dispose()
    assert cleanups == ["cleanup 0", "cleanup 1", "cleanup 2"]


def test_effect_multiple_dependencies():
    x = Signal(1)
    y = Signal(2)
    calls = []

    @effect
    def track_sum(x: int, y: int):
        calls.append(x + y)

    track_sum(x, y)
    assert calls == [3]

    x.value = 10
    assert calls == [3, 12]

    y.value = 5
    assert calls == [3, 12, 15]


def test_effect_dispose_stops_updates():
    x = Signal(0)
    calls = []

    @effect
    def track_value(x: int):
        calls.append(x)

    e = track_value(x)
    assert calls == [0]

    e.dispose()
    x.value = 1
    assert calls == [0]  # No new calls after dispose


def test_effect_cleanup_disposes_properly():
    x = Signal(0)
    cleanup_order = []

    @effect
    def track_with_cleanup(x: int):
        cleanup_order.append(f"effect {x}")

        def cleanup():
            cleanup_order.append(f"cleanup {x}")

        return cleanup

    e = track_with_cleanup(x)
    x.value = 1
    x.value = 2
    e.dispose()

    assert cleanup_order == ["effect 0", "cleanup 0", "effect 1", "cleanup 1", "effect 2", "cleanup 2"]


def test_effect_multiple_cleanups():
    x = Signal("initial")
    resources = []

    @effect
    def manage_resource(val: str):
        resource_id = f"resource for {val}"
        resources.append(resource_id)

        def cleanup():
            resources.remove(resource_id)

        return cleanup

    e = manage_resource(x)
    assert resources == ["resource for initial"]

    x.value = "updated"
    assert resources == ["resource for updated"]

    e.dispose()
    assert resources == []


def test_effect_exception_handling():
    x = Signal(0)
    cleanups = []

    @effect
    def might_fail(val: int):
        if val == 0:
            cleanups.append("setup success")
            return lambda: cleanups.append("cleanup success")
        raise ValueError("Failed")

    might_fail(x)
    assert cleanups == ["setup success"]

    with pytest.raises(ValueError):
        x.value = 1
    assert cleanups == ["setup success", "cleanup success"]


def test_effect_reentrant_updates():
    x = Signal(0)
    y = Signal(0)
    updates = []

    @effect
    def update_y(val: int):
        updates.append(f"x: {val}")
        if val == 1:
            y.value = 1  # This will trigger another effect

    @effect
    def track_y(val: int):
        updates.append(f"y: {val}")

    ex = update_y(x)
    ey = track_y(y)

    assert updates == ["x: 0", "y: 0"]
    updates.clear()

    x.value = 1
    assert updates == ["x: 1", "y: 1"]

    ex.dispose()
    ey.dispose()


def test_effect_multiple_subscriptions():
    """Test that an effect doesn't duplicate subscriptions to the same signal"""
    x = Signal(0)
    calls = []

    @effect
    def track_double(a: int, b: int):  # Same signal passed twice
        calls.append(a + b)

    track_double(x, x)  # Should only trigger once per change
    assert calls == [0]

    x.value = 1
    assert calls == [0, 2]  # Not [0, 1, 1, 2]
