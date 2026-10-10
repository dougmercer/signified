"""Batching for synchronous effect scheduling. The effect queue lives in `signified._core`."""

from collections.abc import Generator
from contextlib import contextmanager

from . import _core


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
    _core.begin_batch()
    try:
        yield
    except BaseException as body_error:
        _core.end_batch()
        try:
            _core.flush()
        except BaseException as flush_error:
            raise BaseExceptionGroup("Signified batch body and effect failures", [body_error, flush_error]) from None
        raise
    else:
        _core.end_batch()
        _core.flush()
