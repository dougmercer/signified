"""Opt-in diagnostics for migrating to signified 0.6."""

from __future__ import annotations

import importlib.util
import os
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from warnings import warn
from weakref import WeakSet

__all__ = ["SignifiedMigrationWarning", "enable_warnings", "disable_warnings", "warnings", "warnings_enabled"]


class SignifiedMigrationWarning(UserWarning):
    """Warning for code whose reactive meaning changed in signified 0.6."""


_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_PACKAGE_ROOT = os.path.dirname(__file__)
WARNINGS_ENABLED = os.getenv("SIGNIFIED_MIGRATION_WARNINGS", "").lower() in _TRUE_ENV_VALUES
_WARNED_COMPUTED_RESULTS: WeakSet[Any] = WeakSet()

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None


def enable_warnings() -> None:
    """Enable migration warnings for subsequent reactive operations."""
    global WARNINGS_ENABLED
    WARNINGS_ENABLED = True


def disable_warnings() -> None:
    """Disable migration warnings."""
    global WARNINGS_ENABLED
    WARNINGS_ENABLED = False


def warnings_enabled() -> bool:
    """Return whether migration warnings are currently enabled."""
    return WARNINGS_ENABLED


@contextmanager
def warnings() -> Generator[None, None, None]:
    """Temporarily enable migration warnings within a `with` block."""
    previous = WARNINGS_ENABLED
    enable_warnings()
    try:
        yield
    finally:
        if not previous:
            disable_warnings()


def _is_reactive(value: Any) -> bool:
    return getattr(type(value), "_IS_REACTIVE", False)


def _contains_reactive(value: Any) -> bool:
    active: set[int] = set()

    def visit(current: Any) -> bool:
        if _is_reactive(current):
            return True

        current_type = type(current)
        if current_type is dict:
            children = (*current.keys(), *current.values())
        elif current_type in {list, tuple, set, frozenset, deque}:
            children = current
        elif np is not None and current_type is np.ndarray and current.dtype == object:
            children = current.flat
        else:
            return False

        identity = id(current)
        if identity in active:
            return False
        active.add(identity)
        try:
            return any(visit(child) for child in children)
        finally:
            active.remove(identity)

    return visit(value)


def _warn_reactive_signal_value() -> None:
    warn(
        "Signal received a reactive value. Signified 0.6 stores that object "
        "without following it; use Binding(source) when source changes should propagate.",
        SignifiedMigrationWarning,
        stacklevel=2,
        skip_file_prefixes=(_PACKAGE_ROOT,),
    )


def _warn_nested_reactive_arguments(kind: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    values = (*args, *kwargs.values())
    if not any(not _is_reactive(value) and _contains_reactive(value) for value in values):
        return
    warn(
        f"{kind} received a container with reactive descendants. Signified 0.6 "
        "only unwraps direct reactive arguments; read .value inside the function "
        "or call deep_unref inside the function.",
        SignifiedMigrationWarning,
        stacklevel=2,
        skip_file_prefixes=(_PACKAGE_ROOT,),
    )


def _warn_reactive_computed_result(owner: Any, result: Any) -> None:
    if owner in _WARNED_COMPUTED_RESULTS or not _contains_reactive(result):
        return
    _WARNED_COMPUTED_RESULTS.add(owner)
    warn(
        "Computed produced a reactive value or a container with reactive descendants. "
        "Signified 0.6 returns that object without recursive resolution; use explicit "
        ".value reads or deep_unref inside the function when resolved values are intended.",
        SignifiedMigrationWarning,
        stacklevel=2,
        skip_file_prefixes=(_PACKAGE_ROOT,),
    )


def _warn_signal_value(value: Any) -> None:
    if _is_reactive(value):
        _warn_reactive_signal_value()
    elif _contains_reactive(value):
        warn(
            "Signal received a container with reactive descendants. Signified 0.6 "
            "stores it unchanged and does not follow its children; use explicit "
            ".value reads or deep_unref inside a computation when resolved values are intended.",
            SignifiedMigrationWarning,
            stacklevel=2,
            skip_file_prefixes=(_PACKAGE_ROOT,),
        )
