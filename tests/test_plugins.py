from typing import Any

import signified._reactive as reactive_module
from signified import Binding, Signal, Variable


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
