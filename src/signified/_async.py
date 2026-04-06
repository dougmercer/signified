"""Async-aware helpers built on top of Signified's synchronous core."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, Literal, TypeVar

from ._reactive import Effect, Signal
from ._scheduler import batch, create_task

__all__ = ["AsyncEffect", "Resource"]

T = TypeVar("T")
ResourceStatus = Literal["idle", "loading", "ready", "error"]


def _close_awaitable(awaitable: Awaitable[object]) -> None:
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


class AsyncEffect:
    """Run async side effects when reactive dependencies change."""

    __slots__ = ("_factory", "_watcher", "_task", "_run_id", "_disposed", "_running_signal", "_error_signal")

    def __init__(self, factory: Callable[[], Awaitable[object]]) -> None:
        self._factory = factory
        self._watcher: Effect | None = None
        self._task: asyncio.Task[None] | None = None
        self._run_id = 0
        self._disposed = False
        self._running_signal: Signal[bool] = Signal(False)
        self._error_signal: Signal[BaseException | None] = Signal(None)
        self._watcher = Effect(self._schedule_refresh)

    @property
    def running(self) -> bool:
        """Return whether the latest effect run is still in flight."""
        return self._running_signal.value

    @property
    def error(self) -> BaseException | None:
        """Return the latest uncancelled effect error, if any."""
        return self._error_signal.value

    def rerun(self) -> None:
        """Schedule a new run using the current dependency values."""
        self._schedule_refresh()

    def _cancel_task(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()

    def _schedule_refresh(self) -> None:
        if self._disposed:
            return

        self._run_id += 1
        run_id = self._run_id
        self._cancel_task()

        try:
            awaitable = self._factory()
        except BaseException as exc:
            with batch():
                self._error_signal.value = exc
                self._running_signal.value = False
            return

        with batch():
            self._error_signal.value = None
            self._running_signal.value = True

        try:
            self._task = create_task(self._drive(awaitable, run_id))
        except BaseException as exc:
            _close_awaitable(awaitable)
            with batch():
                self._error_signal.value = exc
                self._running_signal.value = False

    async def _drive(self, awaitable: Awaitable[object], run_id: int) -> None:
        try:
            await awaitable
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            if self._disposed or run_id != self._run_id:
                return
            with batch():
                self._error_signal.value = exc
                self._running_signal.value = False
            return
        finally:
            if self._task is asyncio.current_task():
                self._task = None

        if self._disposed or run_id != self._run_id:
            return
        with batch():
            self._error_signal.value = None
            self._running_signal.value = False

    def dispose(self) -> None:
        """Cancel any in-flight run and unsubscribe from future changes."""
        if self._disposed:
            return
        self._disposed = True
        self._run_id += 1
        if self._watcher is not None:
            self._watcher.dispose()
            self._watcher = None
        self._cancel_task()
        with batch():
            self._running_signal.value = False


class Resource(Generic[T]):
    """Manage async derived state while exposing synchronous reactive accessors."""

    __slots__ = (
        "_factory",
        "_watcher",
        "_task",
        "_run_id",
        "_disposed",
        "_value_signal",
        "_error_signal",
        "_loading_signal",
        "_status_signal",
    )

    def __init__(self, factory: Callable[[], Awaitable[T]]) -> None:
        self._factory = factory
        self._watcher: Effect | None = None
        self._task: asyncio.Task[None] | None = None
        self._run_id = 0
        self._disposed = False
        self._value_signal: Signal[T | None] = Signal(None)
        self._error_signal: Signal[BaseException | None] = Signal(None)
        self._loading_signal: Signal[bool] = Signal(False)
        self._status_signal: Signal[ResourceStatus] = Signal("idle")
        self._watcher = Effect(self._schedule_refresh)

    @property
    def value(self) -> T | None:
        """Return the latest successful result."""
        return self._value_signal.value

    @property
    def error(self) -> BaseException | None:
        """Return the latest uncancelled error, if any."""
        return self._error_signal.value

    @property
    def loading(self) -> bool:
        """Return whether the latest request is still in flight."""
        return self._loading_signal.value

    @property
    def status(self) -> ResourceStatus:
        """Return the resource lifecycle status."""
        return self._status_signal.value

    @property
    def has_value(self) -> bool:
        """Return whether a successful value has been loaded."""
        return self.value is not None

    def reload(self) -> None:
        """Schedule a fresh request using the current dependency values."""
        self._schedule_refresh()

    def clear(self) -> None:
        """Cancel any in-flight request and reset the resource to idle."""
        self._run_id += 1
        self._cancel_task()
        with batch():
            self._value_signal.value = None
            self._error_signal.value = None
            self._loading_signal.value = False
            self._status_signal.value = "idle"

    def _cancel_task(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()

    def _schedule_refresh(self) -> None:
        if self._disposed:
            return

        self._run_id += 1
        run_id = self._run_id
        self._cancel_task()

        try:
            awaitable = self._factory()
        except BaseException as exc:
            with batch():
                self._error_signal.value = exc
                self._loading_signal.value = False
                self._status_signal.value = "error"
            return

        with batch():
            self._error_signal.value = None
            self._loading_signal.value = True
            self._status_signal.value = "loading"

        try:
            self._task = create_task(self._drive(awaitable, run_id))
        except BaseException as exc:
            _close_awaitable(awaitable)
            with batch():
                self._error_signal.value = exc
                self._loading_signal.value = False
                self._status_signal.value = "error"

    async def _drive(self, awaitable: Awaitable[T], run_id: int) -> None:
        try:
            value = await awaitable
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            if self._disposed or run_id != self._run_id:
                return
            with batch():
                self._error_signal.value = exc
                self._loading_signal.value = False
                self._status_signal.value = "error"
            return
        finally:
            if self._task is asyncio.current_task():
                self._task = None

        if self._disposed or run_id != self._run_id:
            return
        with batch():
            self._value_signal.value = value
            self._error_signal.value = None
            self._loading_signal.value = False
            self._status_signal.value = "ready"

    def dispose(self) -> None:
        """Cancel any in-flight request and unsubscribe from future changes."""
        if self._disposed:
            return
        self._disposed = True
        self._run_id += 1
        if self._watcher is not None:
            self._watcher.dispose()
            self._watcher = None
        self._cancel_task()
        with batch():
            self._loading_signal.value = False
            self._status_signal.value = "idle"
