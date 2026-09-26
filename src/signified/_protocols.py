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

Binary overloads check reactive operands before plain operands, and within each
case try the left operand's method before the right operand's reflected method.
A wrapper itself also implements these protocols, so combining the plain and
reactive cases in one union can infer a spurious nested `Computed` result.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar, Literal, Protocol, SupportsIndex

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
type _IndexLike = SupportsIndex | _ReactiveOf[SupportsIndex]


class _ReactiveOf[V](Protocol):
    """A reactive object whose current value is a `V`."""

    # Match unref's class marker: an ordinary object with .value is not unwrapped.
    _IS_REACTIVE: ClassVar[Literal[True]]

    @property
    def value(self) -> V: ...


class _ReactiveNamespaceOf[V](Protocol):
    """Read-only view of the value behind an rx namespace."""

    @property
    def _source(self) -> _ReactiveOf[V]: ...


class _SupportsEq[OtherT, ResultT](Protocol):
    # Python permits non-bool equality results despite object.__eq__'s stub.
    def __eq__(self, other: OtherT, /) -> ResultT: ...  # pyright: ignore[reportIncompatibleMethodOverride]


class _SupportsNe[OtherT, ResultT](Protocol):
    def __ne__(self, other: OtherT, /) -> ResultT: ...  # pyright: ignore[reportIncompatibleMethodOverride]


class _SupportsCeil[ResultT](Protocol):
    def __ceil__(self) -> ResultT: ...


class _SupportsFloor[ResultT](Protocol):
    def __floor__(self) -> ResultT: ...


class _SupportsNeg[ResultT](Protocol):
    def __neg__(self) -> ResultT: ...


class _SupportsPos[ResultT](Protocol):
    def __pos__(self) -> ResultT: ...


class _SupportsInvert[ResultT](Protocol):
    def __invert__(self) -> ResultT: ...


class _SupportsTrunc[ResultT](Protocol):
    def __trunc__(self) -> ResultT: ...


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


class _SupportsContains(Protocol):
    # Membership coerces this result to bool; __contains__ need not return bool.
    def __contains__(self, other: Any, /) -> object: ...


type _MembershipContainer = _SupportsContains | Iterable[Any] | _SupportsGetItem[int, Any]
"""Membership supports __contains__, iteration, and legacy integer indexing."""


class _SupportsRadd[OtherT, ResultT](Protocol):
    def __radd__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRsub[OtherT, ResultT](Protocol):
    def __rsub__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRmul[OtherT, ResultT](Protocol):
    def __rmul__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRmatmul[OtherT, ResultT](Protocol):
    def __rmatmul__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRtruediv[OtherT, ResultT](Protocol):
    def __rtruediv__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRfloordiv[OtherT, ResultT](Protocol):
    def __rfloordiv__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRmod[OtherT, ResultT](Protocol):
    def __rmod__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRpow[OtherT, ResultT](Protocol):
    def __rpow__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRlshift[OtherT, ResultT](Protocol):
    def __rlshift__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRrshift[OtherT, ResultT](Protocol):
    def __rrshift__(self, other: OtherT, /) -> ResultT: ...


class _SupportsAnd[OtherT, ResultT](Protocol):
    def __and__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRand[OtherT, ResultT](Protocol):
    def __rand__(self, other: OtherT, /) -> ResultT: ...


class _SupportsOr[OtherT, ResultT](Protocol):
    def __or__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRor[OtherT, ResultT](Protocol):
    def __ror__(self, other: OtherT, /) -> ResultT: ...


class _SupportsXor[OtherT, ResultT](Protocol):
    def __xor__(self, other: OtherT, /) -> ResultT: ...


class _SupportsRxor[OtherT, ResultT](Protocol):
    def __rxor__(self, other: OtherT, /) -> ResultT: ...


class _SupportsLt[OtherT, ResultT](Protocol):
    def __lt__(self, other: OtherT, /) -> ResultT: ...


class _SupportsLe[OtherT, ResultT](Protocol):
    def __le__(self, other: OtherT, /) -> ResultT: ...


class _SupportsGt[OtherT, ResultT](Protocol):
    def __gt__(self, other: OtherT, /) -> ResultT: ...


class _SupportsGe[OtherT, ResultT](Protocol):
    def __ge__(self, other: OtherT, /) -> ResultT: ...
