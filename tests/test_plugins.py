import runpy
from pathlib import Path
from typing import Any

import pytest

from signified import Binding, Computed, Signal, Variable, _core, plugins
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
    monkeypatch.setattr(_core.config, "hooks", manager.hook)
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
    monkeypatch.setattr(_core.config, "hooks", manager.hook)
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


@pytest.fixture
def access_tracker(monkeypatch):
    manager = PluginManager()
    monkeypatch.setattr(_core.config, "hooks", manager.hook)
    monkeypatch.setattr(plugins, "plugin_manager", manager)
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


def test_registering_a_plugin_turns_hooks_on_and_unregistering_turns_them_off(monkeypatch) -> None:
    monkeypatch.setattr(_core.config, "hooks", None)
    calls: list[tuple[str, str]] = []
    plugin = Recorder("plugin", calls)
    plugins.plugin_manager.register(plugin)
    try:
        assert _core.config.hooks is plugins.plugin_manager.hook
        Signal(1)
        assert calls == [("plugin", "created")]
    finally:
        plugins.plugin_manager.unregister(plugin)
    assert _core.config.hooks is None
    Signal(2)
    assert calls == [("plugin", "created")]


def test_created_hook_can_read_an_operator_result(monkeypatch) -> None:
    class ReadsOnCreate(RecordingHook):
        def created(self, *, value: Variable[Any]) -> None:
            value.value

    monkeypatch.setattr(_core.config, "hooks", ReadsOnCreate())
    source = Signal(1)
    total = source + 2
    assert total.value == 3
    source.value = 5
    assert total.value == 7


def test_read_hook_that_writes_the_signal_leaves_readers_current(monkeypatch) -> None:
    source = Signal(1)

    class BumpsOnFirstRead(RecordingHook):
        done = False

        def read(self, *, value: Variable[Any]) -> None:
            if value is source and not self.done:
                self.done = True
                source.value = 2

    monkeypatch.setattr(_core.config, "hooks", BumpsOnFirstRead())
    scaled = Computed(lambda: source.value * 10)
    assert scaled.value == 20
    assert scaled.value == 20
