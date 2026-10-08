"""IPython display integration for reactive values."""

from __future__ import annotations

import weakref
from typing import Any

DisplayHandle = Any


__all__ = ["IPythonObserver"]


_ACTIVE_OBSERVERS: weakref.WeakKeyDictionary[Any, list["IPythonObserver"]] = weakref.WeakKeyDictionary()


class IPythonObserver:
    """Observer that updates an IPython display handle when the value changes."""

    def __init__(self, me: Any, handle: DisplayHandle):  # type: ignore
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
        if hasattr(self.handle, "update"):
            self.handle.update(me.value)
