"""Structural protocols and operand spellings used by the reactive operators.

Python's type system has no way to say "whatever `T.__mul__` returns". The
workaround is to describe the shape structurally and carry the result as a type
parameter: when a checker matches a concrete type against `_SupportsMul[OtherT,
ResultT]` it solves `ResultT` by unification. That is what lets the operators
report a user type's own return type instead of falling back to a union of the
operand types, which is only ever correct for operators that are closed over
their operands (`int * int -> int`, `set & set -> set`).

`_ReactiveOf[V]` composes with any of these, so an operator can spell its self
type as `_ReactiveOf[_SupportsMul[Y, R]]` instead of needing a hand-written
reactive twin for every protocol. It is a read-only view, which is what makes it
match the invariant reactive classes at all: `Signal[Vec]` is not assignable to
`_ReactiveMixIn[_SupportsMul[int, Vec]]`, but its `value` does satisfy
`_SupportsMul[int, Vec]`.
"""

from __future__ import annotations

from typing import Literal, Protocol, SupportsIndex

from ._types import HasValue

__all__ = ["_ReactiveOf"]


class _AlwaysTrue(Protocol):
    def __bool__(self) -> Literal[True]: ...


class _AlwaysFalse(Protocol):
    def __bool__(self) -> Literal[False]: ...


type _Truthy = Literal[True] | _AlwaysTrue
"""A value whose truthiness is statically known to be `True`."""

type _Falsy = Literal[False] | _AlwaysFalse | None
"""A value whose truthiness is statically known to be `False`."""


# Operand spellings for the numeric tower and for indexing. `HasValue` is invariant in
# its parameter, so `HasValue[int]` is *not* assignable to `HasValue[float]` and each
# rung has to be listed explicitly rather than relying on int -> float -> complex
# promotion.
type _IntLike = HasValue[bool] | HasValue[int]
type _FloatLike = _IntLike | HasValue[float]
type _ComplexLike = _FloatLike | HasValue[complex]
type _IndexLike = HasValue[SupportsIndex] | HasValue[int]


class _ReactiveOf[V](Protocol):
    """A reactive object whose current value is a `V`."""

    @property
    def value(self) -> V: ...


class _SupportsAdd[OtherT, ResultT](Protocol):
    def __add__(self, other: OtherT, /) -> ResultT: ...


class _SupportsSub[OtherT, ResultT](Protocol):
    def __sub__(self, other: OtherT, /) -> ResultT: ...


class _SupportsMul[OtherT, ResultT](Protocol):
    def __mul__(self, other: OtherT, /) -> ResultT: ...


class _SupportsMatmul[OtherT, ResultT](Protocol):
    def __matmul__(self, other: OtherT, /) -> ResultT: ...


class _SupportsTruediv[OtherT, ResultT](Protocol):
    def __truediv__(self, other: OtherT, /) -> ResultT: ...


class _SupportsFloordiv[OtherT, ResultT](Protocol):
    def __floordiv__(self, other: OtherT, /) -> ResultT: ...


class _SupportsMod[OtherT, ResultT](Protocol):
    def __mod__(self, other: OtherT, /) -> ResultT: ...


class _SupportsPow[OtherT, ResultT](Protocol):
    def __pow__(self, other: OtherT, /) -> ResultT: ...


class _SupportsDivmod[OtherT, ResultT](Protocol):
    def __divmod__(self, other: OtherT, /) -> ResultT: ...


class _SupportsLshift[OtherT, ResultT](Protocol):
    def __lshift__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRshift[OtherT, ResultT](Protocol):
    def __rshift__(self, other: OtherT, /) -> ResultT: ...


class _SupportsGetItem[KeyT, ValueT](Protocol):
    def __getitem__(self, key: KeyT, /) -> ValueT: ...
