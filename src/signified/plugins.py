"""Plugin hooks for observing reactive values.

Hooks only run when ``SIGNIFIED_ENABLE_HOOKS=1`` is set before importing Signified.
"""

from __future__ import annotations

import inspect
import os
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from signified import Variable

__all__ = ["HOOKS_ENABLED", "PluginManager", "hookimpl", "plugin_manager", "pm"]

_ENABLE_HOOKS = os.environ.get("SIGNIFIED_ENABLE_HOOKS")
HOOKS_ENABLED = _ENABLE_HOOKS == "1"

_HOOK_NAMES = ("read", "created", "updated", "named")
_HOOKIMPL_MARK = "_signified_hookimpl"


def hookimpl[F: Callable[..., Any]](fn: F) -> F:
    """Mark a plugin method as the implementation of the hook with the same name."""
    setattr(fn, _HOOKIMPL_MARK, True)
    return fn


class _HookCaller:
    __slots__ = ("impls",)

    def __init__(self) -> None:
        self.impls: tuple[Callable[..., Any], ...] = ()

    def __call__(self, *, value: Variable[Any]) -> None:
        for impl in self.impls:
            impl(value=value)


class _Hooks:
    """The hooks a plugin can implement. Each receives the reactive object as ``value``.

    - ``read``: a reactive value is read.
    - ``created``: a new reactive value is created.
    - ``updated``: a reactive value sends a change notification.
    - ``named``: a reactive value is given a name.
    """

    __slots__ = ("read", "created", "updated", "named")

    def __init__(self) -> None:
        self.read = _HookCaller()
        self.created = _HookCaller()
        self.updated = _HookCaller()
        self.named = _HookCaller()


def _hook_impls(plugin: Any) -> dict[str, Callable[..., Any]]:
    impls = {}
    for name in dir(plugin):
        impl: Any = getattr(plugin, name, None)
        if not getattr(impl, _HOOKIMPL_MARK, False):
            continue
        if name not in _HOOK_NAMES:
            raise ValueError(f"Unknown hook {name!r}; expected one of {', '.join(_HOOK_NAMES)}")
        try:
            inspect.signature(impl).bind(value=None)
        except TypeError:
            raise TypeError(f"Hook implementation {name!r} must accept a `value` keyword argument") from None
        impls[name] = impl
    return impls


class PluginManager:
    """Registry of plugins whose hook implementations run on reactive events.

    Implementations run in reverse registration order, so the most recently
    registered plugin runs first. An exception raised by an implementation
    propagates to the code that triggered the hook.
    """

    def __init__(self) -> None:
        self._plugins: list[tuple[Any, dict[str, Callable[..., Any]]]] = []
        self.hook = _Hooks()

    def register(self, plugin: Any) -> None:
        """Register a plugin instance or module.

        Raises:
            ValueError: If the plugin is already registered or marks an unknown hook.
            TypeError: If a hook implementation does not accept ``value``.
        """
        if any(p is plugin for p, _ in self._plugins):
            raise ValueError(f"Plugin already registered: {plugin!r}")
        self._plugins.append((plugin, _hook_impls(plugin)))
        self._rebuild()

    def unregister(self, plugin: Any) -> None:
        """Unregister a previously registered plugin.

        Raises:
            ValueError: If the plugin is not registered.
        """
        for i, (p, _) in enumerate(self._plugins):
            if p is plugin:
                del self._plugins[i]
                self._rebuild()
                return
        raise ValueError(f"Plugin is not registered: {plugin!r}")

    def _rebuild(self) -> None:
        for name in _HOOK_NAMES:
            caller: _HookCaller = getattr(self.hook, name)
            caller.impls = tuple(impls[name] for _, impls in reversed(self._plugins) if name in impls)


plugin_manager = PluginManager()

# Backwards-compatible alias.
pm = plugin_manager
