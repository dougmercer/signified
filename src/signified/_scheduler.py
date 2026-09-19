"""Synchronous effect scheduling. All state belongs to one reactive thread."""

from collections import OrderedDict
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Protocol
from weakref import ReferenceType, ref


class _ScheduledEffect(Protocol):
    _active: bool

    def _run(self) -> None: ...


_pending: OrderedDict[int, ReferenceType[_ScheduledEffect]] = OrderedDict()
_batch_depth = 0
_notification_depth = 0
_flushing = False
_notified: set[int] = set()
_MAX_RUNS_PER_EFFECT = 100


def _raise_errors(errors: list[Exception]) -> None:
    """Raise one failure directly and several as an ExceptionGroup."""
    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ExceptionGroup("Signified effect failures", errors)


def _run_pending(
    effect_ref: ReferenceType[_ScheduledEffect],
    runs: dict[ReferenceType[_ScheduledEffect], int],
    errors: list[Exception],
) -> bool:
    # Keep the strong local reference scoped to one execution, not the flush.
    effect = effect_ref()
    if effect is None or not effect._active:
        return True
    count = runs.get(effect_ref, 0) + 1
    runs[effect_ref] = count
    if count > _MAX_RUNS_PER_EFFECT:
        errors.append(RuntimeError(f"Effect did not settle after {_MAX_RUNS_PER_EFFECT} runs"))
        return False
    try:
        effect._run()
    except Exception as error:
        errors.append(error)
    return True


def _flush() -> None:
    global _flushing
    if not _pending or _flushing or _batch_depth or _notification_depth:
        return
    _flushing = True
    errors: list[Exception] = []
    # Weak keys do not retain effects; dead entries can wait until flush exit.
    runs: dict[ReferenceType[_ScheduledEffect], int] = {}
    try:
        while _pending:
            _, effect_ref = _pending.popitem(last=False)
            if not _run_pending(effect_ref, runs, errors):
                break
    finally:
        _pending.clear()
        _flushing = False
    _raise_errors(errors)


def schedule(effect: _ScheduledEffect) -> None:
    if not effect._active:
        return
    # Replace stale entries if an object ID is reused before the batch flushes.
    _pending[id(effect)] = ref(effect)
    _flush()


def discard(effect: _ScheduledEffect) -> None:
    _pending.pop(id(effect), None)


def notify(identity: int, callback: Callable[[], None]) -> None:
    """Invalidate a full notification wave before executing its effects."""
    global _notification_depth
    if identity in _notified:
        return
    _notified.add(identity)
    _notification_depth += 1
    try:
        callback()
    finally:
        _notification_depth -= 1
        if not _notification_depth:
            _notified.clear()
    if not _notification_depth and _pending:
        _flush()


@contextmanager
def batch() -> Generator[None, None, None]:
    """Defer effects until the outermost synchronous batch exits.

    Writes are immediate and computed reads remain current. Newly created
    effects are deferred too. Nested batches combine; cascading writes may run
    an effect more than once. This is not a transaction: errors do not roll back
    writes, and ordinary reads can see intermediate state. Do not span await or
    use the reactive graph from multiple threads.

    One failing effect raises its exception directly; several are raised as an
    ExceptionGroup. A body exception alone is re-raised unchanged; simultaneous
    body and flush failures are grouped together.
    """
    global _batch_depth
    _batch_depth += 1
    try:
        yield
    except BaseException as body_error:
        _batch_depth -= 1
        try:
            _flush()
        except BaseException as flush_error:
            raise BaseExceptionGroup("Signified batch body and effect failures", [body_error, flush_error]) from None
        raise
    else:
        _batch_depth -= 1
        _flush()
