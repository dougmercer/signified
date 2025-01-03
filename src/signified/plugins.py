from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pluggy

__all__ = ["hookimpl", "pm"]

if TYPE_CHECKING:
    from signified import Variable

hookspec = pluggy.HookspecMarker("signified")
hookimpl = pluggy.HookimplMarker("signified")


class SignifiedHookSpec:
    """Hook specifications for the Signified library."""

    @hookspec
    def read(self, value: Variable[Any, Any]) -> None:
        """Called when a new reactive value is created."""

    @hookspec
    def created(self, value: Variable[Any, Any]) -> None:
        """Called when a new reactive value is created."""

    @hookspec
    def updated(self, value: Variable[Any, Any]) -> None:
        """Called when a reactive value is updated."""

    @hookspec
    def named(self, value: Variable[Any, Any]) -> None:
        """Called when a reactive value has been named."""


pm = pluggy.PluginManager("signified")
pm.add_hookspecs(SignifiedHookSpec)
