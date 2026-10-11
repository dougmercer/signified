"""Batching for synchronous effect scheduling. The effect queue lives in `signified._core`."""

from contextlib import AbstractContextManager

from . import _core


def batch() -> AbstractContextManager[None]:
    """Defer effects until the outermost synchronous batch exits.

    Writes are immediate and computed reads remain current. Newly created
    effects are deferred too. Nested batches combine; cascading writes may run
    an effect more than once. This is not a transaction: errors do not roll back
    writes, and ordinary reads can see intermediate state. A batch defers only
    work queued on the thread that entered it. Do not span await.

    One failing effect raises its exception directly; several are raised as an
    ExceptionGroup. A body exception alone is re-raised unchanged; simultaneous
    body and flush failures are grouped together.
    """
    return _core.Batch()
