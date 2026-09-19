"""Tests for opt-in migration diagnostics."""

import warnings

import pytest

from signified import Binding, Computed, Effect, Signal, computed, effect, migration


def test_migration_warnings_are_disabled_by_default():
    migration.disable_warnings()

    with warnings.catch_warnings():
        warnings.simplefilter("error", migration.SignifiedMigrationWarning)
        Signal(Signal(1))


def test_warns_when_signal_receives_a_reactive_value():
    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning, match="Signal received"):
            outer = Signal(Signal(1))
        with pytest.warns(migration.SignifiedMigrationWarning, match="Signal received"):
            outer.value = Signal(2)


@pytest.mark.parametrize("plain", [False, True])
def test_binding_internal_holder_does_not_emit_migration_warnings(plain):
    with migration.warnings(), warnings.catch_warnings():
        warnings.simplefilter("error", migration.SignifiedMigrationWarning)
        binding = Binding(1 if plain else Signal(1))
        assert binding.value == 1
        binding.set(Signal(2))
        assert binding.value == 2
        binding.set(3)
        assert binding.value == 3
        binding.derive(lambda previous: previous * 2)
        assert binding.value == 6
        with binding.at(4):
            assert binding.value == 4
        assert binding.value == 6


def test_binding_rebind_preserves_migration_warnings_in_effects():
    binding = Binding(0)

    def observe():
        if binding.value:
            Signal(Signal(1))

    watcher = Effect(observe)
    try:
        with migration.warnings(), warnings.catch_warnings():
            warnings.simplefilter("error", migration.SignifiedMigrationWarning)
            with pytest.raises(migration.SignifiedMigrationWarning, match="Signal received"):
                binding.set(Signal(1))
            # The warning came from the effect after the rebind was applied.
            assert binding.value == 1
    finally:
        watcher.dispose()


def test_binding_still_warns_for_user_supplied_nested_contents():
    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning, match="container"):
            Binding([Signal(1)])


@pytest.mark.parametrize("decorator", [computed, effect])
def test_warns_for_reactive_descendants_in_function_arguments(decorator):
    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning, match="reactive descendants"):
            result = decorator(lambda value: value)([Signal(1)])
    if hasattr(result, "dispose"):
        result.dispose()


def test_direct_reactive_function_argument_does_not_warn():
    with migration.warnings(), warnings.catch_warnings(record=True) as seen:
        result = computed(lambda value: value)(Signal(1))
        assert result.value == 1

    assert not [warning for warning in seen if warning.category is migration.SignifiedMigrationWarning]


def test_warns_once_when_computed_returns_a_reactive_value():
    source = Signal(1)
    result = Computed(lambda: source)

    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning, match="Computed produced"):
            assert result.value is source
        result.invalidate()
        with warnings.catch_warnings(record=True) as seen:
            assert result.value is source

    assert not [warning for warning in seen if warning.category is migration.SignifiedMigrationWarning]


def test_warns_for_nested_signal_contents_and_computed_results():
    child = Signal(1)
    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning, match="container"):
            source = Signal({"child": child})
        with pytest.warns(migration.SignifiedMigrationWarning, match="container"):
            source.value = [child]
        result = Computed(lambda: [child])
        with pytest.warns(migration.SignifiedMigrationWarning, match="descendants"):
            assert result.value[0] is child


def test_diagnostics_do_not_read_reactives_or_consume_unknown_iterables():
    class Opaque:
        def __iter__(self):
            raise AssertionError("must not inspect")

    child = Computed(lambda: pytest.fail("must not read"))
    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning):
            Signal([child])
        Signal(Opaque())


def test_warning_as_error_restores_computation_tracking():
    source = Signal(1)
    result = Computed(lambda: source)
    with migration.warnings(), warnings.catch_warnings():
        warnings.simplefilter("error", migration.SignifiedMigrationWarning)
        with pytest.raises(migration.SignifiedMigrationWarning):
            _ = result.value
    other = Computed(lambda: source.value * 2)
    assert other.value == 2
    source.value = 2
    assert other.value == 4


def test_direct_operator_calls_do_not_diagnose_container_arguments():
    child = Signal(1)
    source = Signal([])
    fn = Signal(len)
    with migration.warnings(), warnings.catch_warnings():
        warnings.simplefilter("error", migration.SignifiedMigrationWarning)
        added = source + [child]
        assert source.rx.eq([child]).value is False
        assert fn([child]).value == 1

    # Result diagnostics still belong to Computed itself.
    with migration.warnings():
        with pytest.warns(migration.SignifiedMigrationWarning, match="descendants"):
            assert added.value == [child]
