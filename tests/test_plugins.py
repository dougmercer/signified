import runpy
from pathlib import Path
from typing import Any

import pytest

import signified._reactive as reactive_module
from signified import Binding, Computed, Signal, Variable, plugins


class RecordingHook:
    def __init__(self) -> None:
        self.updated_values: list[Variable[Any]] = []

    def created(self, *, value: Variable[Any]) -> None:
        pass

    def read(self, *, value: Variable[Any]) -> None:
        pass

    def updated(self, *, value: Variable[Any]) -> None:
        self.updated_values.append(value)


class RecordingPluginManager:
    def __init__(self) -> None:
        self.hook = RecordingHook()


def enable_recording_hooks(monkeypatch) -> RecordingHook:
    manager = RecordingPluginManager()
    monkeypatch.setattr(reactive_module, "HOOKS_ENABLED", True)
    monkeypatch.setattr(reactive_module, "plugin_manager", manager)
    return manager.hook


def test_updated_hook_runs_for_signal_update(monkeypatch) -> None:
    hook = enable_recording_hooks(monkeypatch)
    signal = Signal([])
    hook.updated_values.clear()

    signal.update()

    assert hook.updated_values == [signal]


def test_updated_hook_runs_only_when_a_binding_rebind_changes_its_value(monkeypatch) -> None:
    hook = enable_recording_hooks(monkeypatch)
    binding = Binding(Signal(1))
    assert binding.value == 1
    hook.updated_values.clear()

    binding.set(Signal(1))
    assert binding.value == 1
    assert binding not in hook.updated_values

    binding.set(Signal(2))
    assert binding.value == 2
    assert hook.updated_values[-1] is binding


def test_updated_hook_runs_for_item_assignment(monkeypatch) -> None:
    hook = enable_recording_hooks(monkeypatch)
    signal = Signal([0])
    hook.updated_values.clear()

    signal[0] = 1

    assert hook.updated_values == [signal]


def test_updated_hook_runs_for_forwarded_attribute_assignment(monkeypatch) -> None:
    class Box:
        def __init__(self) -> None:
            self.count = 0

    hook = enable_recording_hooks(monkeypatch)
    signal = Signal(Box())
    hook.updated_values.clear()

    signal.count = 1

    assert hook.updated_values == [signal]


def test_updated_hook_runs_for_item_deletion(monkeypatch) -> None:
    hook = enable_recording_hooks(monkeypatch)
    signal = Signal([1, 2, 3])
    hook.updated_values.clear()

    del signal[1]

    assert signal.value == [1, 3]
    assert hook.updated_values == [signal]


@pytest.fixture
def access_tracker(monkeypatch):
    manager, hookimpl = plugins._make_pluggy_pm()
    monkeypatch.setattr(reactive_module, "HOOKS_ENABLED", True)
    monkeypatch.setattr(reactive_module, "plugin_manager", manager)
    monkeypatch.setattr(plugins, "plugin_manager", manager)
    monkeypatch.setattr(plugins, "hookimpl", hookimpl)
    example = Path(__file__).resolve().parents[1] / "examples" / "plugins" / "access_tracker.py"
    return runpy.run_path(str(example))["tracker"]


def test_access_tracker_counts_only_actual_reads_and_writes(access_tracker, capsys):
    signal = Signal(1).with_name("source")
    stats = access_tracker.get_stats(signal)
    assert stats.read_count == 0
    assert stats.write_count == 0
    assert [event.value for event in stats.value_history] == [1]

    assert signal.value == 1
    signal.value = 2
    signal.value = 2
    access_tracker.print_summary()

    assert "Value source:" in capsys.readouterr().out
    assert stats.read_count == 1
    assert stats.write_count == 1
    assert [event.value for event in stats.value_history] == [1, 2]


def test_access_tracker_preserves_lazy_computation(access_tracker):
    source = Signal(1)
    derived = Computed(lambda: source.value * 2)
    source_stats = access_tracker.get_stats(source)
    derived_stats = access_tracker.get_stats(derived)
    assert source_stats.read_count == 0
    assert derived_stats.read_count == 0
    assert derived_stats.write_count == 0

    assert derived.value == 2
    assert derived.value == 2
    assert source_stats.read_count == 1
    assert derived_stats.read_count == 2
    assert derived_stats.write_count == 1

    source.value = 2
    assert derived_stats.write_count == 1
    assert derived.value == 4
    assert source_stats.read_count == 2
    assert derived_stats.read_count == 3
    assert derived_stats.write_count == 2
    assert [event.value for event in derived_stats.value_history] == [None, 2, 4]


def test_access_tracker_preserves_computation_errors_and_recovery(access_tracker):
    source = Signal(0)
    derived = Computed(lambda: 10 / source.value)

    with pytest.raises(ZeroDivisionError):
        _ = derived.value

    source.value = 2
    assert derived.value == 5
    stats = access_tracker.get_stats(derived)
    assert stats.read_count == 2
    assert stats.write_count == 2
    assert stats.last_value == 5
