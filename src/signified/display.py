"""IPython display integration for reactive values."""

from typing import Any

from IPython.display import DisplayHandle


class IPythonObserver:
    """Observer that updates IPython display when value changes."""

    def __init__(self, me: Any, handle: DisplayHandle):
        self.me = me
        self.handle = handle
        me.subscribe(self)

    def update(self) -> None:
        self.handle.update(self.me.value)


class Echo:
    """Observer that prints value changes to stdout."""

    def __init__(self, me: Any):
        self.me = me
        me.subscribe(self)

    def update(self) -> None:
        print(self.me.value)
