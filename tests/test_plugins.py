from typing import Any

import pytest

import signified._reactive as reactive_module
from signified import Binding, Signal, Variable
from signified.plugins import PluginManager, hookimpl


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


class Recorder:
    def __init__(self, label: str, calls: list[tuple[str, str]]) -> None:
        self.label = label
        self.calls = calls

    @hookimpl
    def created(self, value: Variable[Any]) -> None:
        self.calls.append((self.label, "created"))

    def read(self, value: Variable[Any]) -> None:
        self.calls.append((self.label, "read"))


def test_plugin_manager_calls_marked_impls_most_recent_first(monkeypatch) -> None:
    manager = PluginManager()
    monkeypatch.setattr(reactive_module, "HOOKS_ENABLED", True)
    monkeypatch.setattr(reactive_module, "plugin_manager", manager)
    calls: list[tuple[str, str]] = []
    first, second = Recorder("first", calls), Recorder("second", calls)
    manager.register(first)
    manager.register(second)

    signal = Signal(1)
    assert signal.value == 1

    assert calls == [("second", "created"), ("first", "created")]

    manager.unregister(second)
    calls.clear()
    Signal(2)
    assert calls == [("first", "created")]


def test_plugin_manager_rejects_duplicate_and_unknown_plugins() -> None:
    manager = PluginManager()
    plugin = Recorder("plugin", [])
    manager.register(plugin)

    with pytest.raises(ValueError, match="already registered"):
        manager.register(plugin)
    manager.unregister(plugin)
    with pytest.raises(ValueError, match="not registered"):
        manager.unregister(plugin)


def test_plugin_manager_validates_hook_impls() -> None:
    class Misspelled:
        @hookimpl
        def craeted(self, value: Variable[Any]) -> None:
            pass

    class WrongArgument:
        @hookimpl
        def created(self, vaule: Variable[Any]) -> None:
            pass

    manager = PluginManager()
    with pytest.raises(ValueError, match="Unknown hook 'craeted'"):
        manager.register(Misspelled())
    with pytest.raises(TypeError, match="must accept a `value` keyword argument"):
        manager.register(WrongArgument())
