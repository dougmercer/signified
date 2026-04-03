import gc
import sys
from typing import Any
from unittest.mock import MagicMock

from signified import Signal
from signified import _ipython as display_module
from signified._ipython import IPythonObserver


class MockDisplayHandle:
    def __init__(self) -> None:
        self.updated_values: list[Any] = []

    def update(self, value: Any) -> None:
        self.updated_values.append(value)


def test_ipython_observer_kept_alive_without_external_reference(monkeypatch) -> None:
    monkeypatch.setattr(display_module, "_HAS_IPYTHON", True)

    signal = Signal(1)
    handle = MockDisplayHandle()

    IPythonObserver(signal, handle)
    gc.collect()

    signal.value = 2
    assert handle.updated_values == [2]


def test_ipython_display_subscribes_updates(monkeypatch) -> None:
    monkeypatch.setattr(display_module, "_HAS_IPYTHON", True)

    shown: dict[str, Any] = {}

    def fake_display(value: Any, display_id: bool = False) -> MockDisplayHandle:
        assert display_id is True
        handle = MockDisplayHandle()
        shown["initial_value"] = value
        shown["handle"] = handle
        return handle

    mock_ipython_display = MagicMock()
    mock_ipython_display.display = fake_display
    monkeypatch.setitem(sys.modules, "IPython", MagicMock())
    monkeypatch.setitem(sys.modules, "IPython.display", mock_ipython_display)

    signal = Signal(10)
    signal._ipython_display_()
    gc.collect()

    signal.value = 11
    handle = shown["handle"]

    assert shown["initial_value"] == 10
    assert handle.updated_values == [11]
