"""IPython display integration for reactive values."""

from __future__ import annotations

import importlib.util
import weakref
from typing import Any

_HAS_IPYTHON = importlib.util.find_spec("IPython") is not None
DisplayHandle = Any


__all__ = ["IPythonObserver"]


_ACTIVE_OBSERVERS: weakref.WeakKeyDictionary[Any, list["IPythonObserver"]] = weakref.WeakKeyDictionary()


class IPythonObserver:
    """Observer that updates IPython display when value changes.

    Only works if IPython is available.
    """

    def __init__(self, me: Any, handle: DisplayHandle):  # type: ignore
        if not _HAS_IPYTHON:
            raise ImportError("IPython is required for IPythonObserver but is not installed")

        # Observers are stored as weakrefs by reactive values, so keep a strong
        # reference here to prevent immediate collection.
        _ACTIVE_OBSERVERS.setdefault(me, []).append(self)
        self.me_ref = weakref.ref(me)
        self.handle = handle
        me.subscribe(self)

    def update(self) -> None:
        me = self.me_ref()
        if me is None:
            return
        if _HAS_IPYTHON and hasattr(self.handle, "update"):
            self.handle.update(me.value)
