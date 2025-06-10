"""IPython display integration for reactive values."""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Any

HAS_IPYTHON = importlib.util.find_spec("IPython") is not None
if TYPE_CHECKING and HAS_IPYTHON:
    from IPython.display import DisplayHandle  # pyright: ignore[reportMissingImports]
else:
    DisplayHandle = Any


class IPythonObserver:
    """Observer that updates IPython display when value changes.

    Only works if IPython is available.
    """

    def __init__(self, me: Any, handle: DisplayHandle):  # type: ignore
        if not HAS_IPYTHON:
            raise ImportError("IPython is required for IPythonObserver but is not installed")

        self.me = me
        self.handle = handle
        me.subscribe(self)

    def update(self) -> None:
        if HAS_IPYTHON and hasattr(self.handle, "update"):
            self.handle.update(self.me.value)
