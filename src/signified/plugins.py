from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from signified import Variable

__all__ = ["hookimpl", "pm"]

_ENABLE_HOOKS = os.environ.get("SIGNIFIED_ENABLE_HOOKS")


def _noop(*args: Any, **kwargs: Any) -> None:
    pass


class _NoOpHook:
    __slots__ = ()
    read = staticmethod(_noop)
    created = staticmethod(_noop)
    updated = staticmethod(_noop)
    named = staticmethod(_noop)


class _NoOpPM:
    __slots__ = ("hook",)

    def __init__(self) -> None:
        self.hook = _NoOpHook()

    def register(self, plugin: Any, name: str | None = None) -> None:
        pass

    def unregister(self, plugin: Any) -> None:
        pass


def _identity(fn: Any) -> Any:
    return fn


def _make_pluggy_pm() -> Any:
    import pluggy

    hookspec = pluggy.HookspecMarker("signified")

    class SignifiedHookSpec:
        """Hook specifications for the Signified library."""

        @hookspec
        def read(self, value: Variable[Any]) -> None:
            """Called when a reactive value is read."""

        @hookspec
        def created(self, value: Variable[Any]) -> None:
            """Called when a new reactive value is created."""

        @hookspec
        def updated(self, value: Variable[Any]) -> None:
            """Called when a reactive value is updated."""

        @hookspec
        def named(self, value: Variable[Any]) -> None:
            """Called when a reactive value has been named."""

    _pm = pluggy.PluginManager("signified")
    _pm.add_hookspecs(SignifiedHookSpec)
    return _pm, pluggy.HookimplMarker("signified")


if _ENABLE_HOOKS == "1":
    # Force-enable: pluggy must be installed
    pm, hookimpl = _make_pluggy_pm()
else:
    # Force-disable: use no-op
    pm = _NoOpPM()
    hookimpl = _identity
