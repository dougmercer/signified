"""Tests for opt-in migration diagnostics."""

import warnings

import pytest

from signified import Computed, Signal, computed, effect, migration


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
