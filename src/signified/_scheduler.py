"""Scheduling helpers for batched observer flushes and async task creation."""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from ._types import _OrderedWeakSet, _SupportsUpdate

__all__ = ["batch", "create_task"]

_GLOBAL_BATCH_DEPTH = 0
_GLOBAL_IS_FLUSHING_BATCH = False
_BATCH_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar("signified_batch_depth", default=0)
_IS_FLUSHING_BATCH: contextvars.ContextVar[bool] = contextvars.ContextVar("signified_is_flushing_batch", default=False)
_PENDING_BATCH_OBSERVERS: contextvars.ContextVar[_OrderedWeakSet[_SupportsUpdate] | None] = contextvars.ContextVar(
    "signified_pending_batch_observers",
    default=None,
)
_create_task: Callable[[Any], Any] | None = None
_TASK_CONTEXT_DEFAULTS: dict[contextvars.ContextVar[Any], Any] = {
    _BATCH_DEPTH: 0,
    _IS_FLUSHING_BATCH: False,
    _PENDING_BATCH_OBSERVERS: None,
}


def register_task_context_default(var: contextvars.ContextVar[Any], value: Any) -> None:
    """Reset ``var`` to ``value`` when spawning a background task."""
    _TASK_CONTEXT_DEFAULTS[var] = value


def _get_pending_batch_observers() -> _OrderedWeakSet[_SupportsUpdate]:
    pending = _PENDING_BATCH_OBSERVERS.get()
    if pending is None:
        pending = _OrderedWeakSet[_SupportsUpdate]()
        _PENDING_BATCH_OBSERVERS.set(pending)
    return pending


def should_batch_observers() -> bool:
    """Return whether non-reactive observers should be queued."""
    if _GLOBAL_BATCH_DEPTH == 0 and not _GLOBAL_IS_FLUSHING_BATCH:
        return False
    return _BATCH_DEPTH.get() > 0 or _IS_FLUSHING_BATCH.get()


def queue_batch_observer(observer: _SupportsUpdate) -> None:
    """Queue a non-reactive observer to run when the current batch flushes."""
    _get_pending_batch_observers().add(observer)


def flush_pending_batch_observers() -> None:
    """Flush queued observers until no more deferred work remains."""
    global _GLOBAL_IS_FLUSHING_BATCH

    if _IS_FLUSHING_BATCH.get():
        return

    flushing_token = _IS_FLUSHING_BATCH.set(True)
    _GLOBAL_IS_FLUSHING_BATCH = True
    try:
        pending = _get_pending_batch_observers()
        while pending:
            observers = tuple(pending)
            pending.clear()
            for observer in observers:
                observer.update()
    finally:
        _GLOBAL_IS_FLUSHING_BATCH = False
        _IS_FLUSHING_BATCH.reset(flushing_token)


@contextmanager
def batch() -> Generator[None, None, None]:
    """Group writes and flush non-reactive observers once on outer exit."""
    global _GLOBAL_BATCH_DEPTH

    depth = _BATCH_DEPTH.get()
    depth_token = _BATCH_DEPTH.set(depth + 1)
    _GLOBAL_BATCH_DEPTH += 1
    try:
        yield
    finally:
        _GLOBAL_BATCH_DEPTH -= 1
        _BATCH_DEPTH.reset(depth_token)
        if depth == 0:
            flush_pending_batch_observers()


def create_task(coro: Any) -> Any:
    """Create an async task through a centralized hook."""
    if _create_task is not None:
        return _create_task(coro)
    context = contextvars.copy_context()
    for var, value in _TASK_CONTEXT_DEFAULTS.items():
        context.run(var.set, value)
    return asyncio.create_task(coro, context=context)
