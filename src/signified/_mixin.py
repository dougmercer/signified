"""Core reactive programming functionality."""

from __future__ import annotations

import math
import operator
from collections.abc import Sized
from typing import TYPE_CHECKING, Any, Callable, Literal, SupportsAbs, Union, overload

from ._protocols import (
    _ComplexLike,
    _Falsy,
    _FloatLike,
    _IndexLike,
    _IntLike,
    _ReactiveOf,
    _SupportsAdd,
    _SupportsDivmod,
    _SupportsFloordiv,
    _SupportsGetItem,
    _SupportsInvert,
    _SupportsLshift,
    _SupportsMatmul,
    _SupportsMod,
    _SupportsMul,
    _SupportsNeg,
    _SupportsPos,
    _SupportsPow,
    _SupportsRshift,
    _SupportsSub,
    _SupportsTruediv,
    _SupportsTrunc,
    _Truthy,
)
from ._types import HasValue

if TYPE_CHECKING:
    from datetime import date, timedelta

    from ._reactive import Computed

__all__ = ["_ReactiveMixIn"]


def _ternary[A, B](a: A, b: B, condition: object) -> A | B:
    return a if condition else b


class _ReactiveNamespace[T]:
    """Helper methods available under `signal_or_computed.rx`."""

    __slots__ = ("_source",)

    def __init__(self, source: "_ReactiveMixIn[T]") -> None:
        self._source = source

    def map[R](self, fn: Callable[[T], R]) -> Computed[R]:
        """Return a reactive value by applying `fn` to the source.

        Args:
            fn: Function used to transform the current source value.

        Returns:
            A reactive value for `fn(source.value)`.

        Example:
            ```py
            >>> s = Signal(4)
            >>> doubled = s.rx.map(lambda x: x * 2)
            >>> doubled.value
            8
            >>> s.value = 5
            >>> doubled.value
            10

            ```
        """
        return _computed_call(fn, self._source)

    def effect(self, fn: Callable[[T], None]) -> "Effect":
        """Eagerly run `fn` for side effects whenever the source changes.

        `fn` runs synchronously on creation and after updates, without a
        `.value` read. Inside batch(), initial and subsequent runs are deferred
        and pending notifications coalesce.

        This is a convenience wrapper around [Effect][signified.Effect]. The source value is
        passed as the single argument to `fn` on each run. For effects that need
        to read multiple reactive values, use [Effect][signified.Effect] directly.

        The effect is active as long as the caller holds the returned [Effect][signified.Effect]
        instance. Call [Effect.dispose][signified.Effect.dispose] to stop it explicitly.

        Args:
            fn: Callback that receives the current source value on each change.

        Returns:
            An [Effect][signified.Effect] instance whose lifetime controls the subscription.

        Example:
            ```py
            >>> seen = []
            >>> s = Signal(1)
            >>> e = s.rx.effect(seen.append)
            >>> seen
            [1]
            >>> s.value = 2
            >>> s.value = 3
            >>> seen
            [1, 2, 3]
            >>> e.dispose()
            >>> s.value = 99
            >>> seen
            [1, 2, 3]

            ```
        """
        source = self._source
        return Effect(lambda: fn(source.value))

    def tap(self, fn: Callable[[T], Any]) -> Computed[T]:
        """Lazily call `fn` on evaluation and pass through the source value.

        This returns a cached [Computed][signified.Computed]: repeated reads
        without invalidation do not repeat the callback, and unread intermediate
        values are skipped. Keep the result alive. Use `rx.effect` for eager
        side effects, or `untracked()` to inspect a value without subscribing.

        Example:
            ```py
            >>> seen = []
            >>> s = Signal(1)
            >>> passthrough = s.rx.tap(seen.append)
            >>> s.value = 2
            >>> seen
            []
            >>> passthrough.value
            2
            >>> seen
            [2]

            ```
        """

        def _tap(value: T) -> T:
            fn(value)
            return value

        return _computed_call(_tap, self._source)

    def len[S: Sized](self: _ReactiveNamespace[S]) -> Computed[int]:
        """Return a reactive value for ``len(source.value)``.

        Returns:
            A reactive value for ``len(source.value)``.

        Example:
            ```py
            >>> s = Signal([1, 2, 3])
            >>> length = s.rx.len()
            >>> length.value
            3
            >>> s.value = [10]
            >>> length.value
            1

            ```
        """
        return _computed_call(len, self._source)

    def is_(self, other: Any) -> Computed[bool]:
        """Return a reactive value for identity check ``source.value is other``.

        Args:
            other: Value to compare against with identity semantics.

        Returns:
            A reactive value for ``source.value is other``.

        Example:
            ```py
            >>> marker = object()
            >>> s = Signal(marker)
            >>> result = s.rx.is_(marker)
            >>> result.value
            True
            >>> s.value = object()
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.is_, self._source, other)

    def is_not(self, other: Any) -> Computed[bool]:
        """Return a reactive value for identity check ``source.value is not other``.

        Args:
            other: Value to compare against with identity semantics.

        Returns:
            A reactive value for ``source.value is not other``.

        Example:
            ```py
            >>> marker = object()
            >>> s = Signal(marker)
            >>> result = s.rx.is_not(marker)
            >>> result.value
            False
            >>> s.value = object()
            >>> result.value
            True

            ```
        """
        return _computed_call(operator.is_not, self._source, other)

    def in_(self, container: Any) -> Computed[bool]:
        """Return a reactive value for containment check ``source.value in container``.

        Args:
            container: Value checked for membership, e.g. list/string/set.

        Returns:
            A reactive value for ``source.value in container``.

        Example:
            ```py
            >>> needle = Signal("a")
            >>> haystack = Signal("cat")
            >>> result = needle.rx.in_(haystack)
            >>> result.value
            True
            >>> needle.value = "z"
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.contains, container, self._source)

    def contains(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `other` is in `self._source`.

        Args:
            other: The value to check for containment.

        Returns:
            A reactive value for ``other in source.value``.

        Example:
            ```py
            >>> s = Signal([1, 2, 3, 4])
            >>> result = s.rx.contains(3)
            >>> result.value
            True
            >>> s.value = [5, 6, 7, 8]
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.contains, self._source, other)

    def eq(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether ``source.value == other``.

        Args:
            other: Value to compare against.

        Returns:
            A reactive value for ``source.value == other``.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = s.rx.eq(10)
            >>> result.value
            True
            >>> s.value = 25
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.eq, self._source, other)

    def ne(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether ``source.value != other``.

        Comparisons between reactive objects use identity. Use this method to
        compare their wrapped values without changing how reactive objects behave
        in sets and dictionaries.

        Args:
            other: Value to compare against.

        Returns:
            A reactive value for ``source.value != other``.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = s.rx.ne(10)
            >>> result.value
            False
            >>> s.value = 25
            >>> result.value
            True

            ```
        """
        return _computed_call(operator.ne, self._source, other)

    @overload
    def where[A, B, C: _Truthy](self: _ReactiveNamespace[C], a: HasValue[A], b: HasValue[B]) -> Computed[A]: ...

    @overload
    def where[A, B, C: _Falsy](self: _ReactiveNamespace[C], a: HasValue[A], b: HasValue[B]) -> Computed[B]: ...

    @overload
    def where[A, B](self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]: ...

    def where[A, B](self, a: HasValue[A], b: HasValue[B]) -> Computed[Any]:
        """Return a reactive value for ``a`` if ``source`` is truthy, else ``b``.

        When the source type guarantees truthiness or falsiness (a literal bool,
        `None`, or a literal-returning `__bool__`), the result type narrows to the
        selected branch. An ordinary `Signal[bool]` retains both branch types.

        Args:
            a: The value to return if source is truthy.
            b: The value to return if source is falsy.

        Returns:
            A reactive value for ``a if source.value else b``.

        Example:
            ```py
            >>> condition = Signal(True)
            >>> result = condition.rx.where("Yes", "No")
            >>> result.value
            'Yes'
            >>> condition.value = False
            >>> result.value
            'No'

            ```
        """

        return _computed_call(_ternary, a, b, self._source)

    @overload
    def as_bool[C: _Truthy](self: _ReactiveNamespace[C]) -> Computed[Literal[True]]: ...

    @overload
    def as_bool[C: _Falsy](self: _ReactiveNamespace[C]) -> Computed[Literal[False]]: ...

    @overload
    def as_bool(self) -> Computed[bool]: ...

    def as_bool(self) -> Computed[Any]:
        """Return a reactive value for the boolean value of ``self._source``.

        Note:
            ``__bool__`` cannot be implemented to return a non-``bool``, so it is provided as a method.

        Returns:
            A reactive value for ``bool(source.value)``.

        Example:
            ```py
            >>> s = Signal(1)
            >>> result = s.rx.as_bool()
            >>> result.value
            True
            >>> s.value = 0
            >>> result.value
            False

            ```
        """
        return _computed_call(bool, self._source)


class _ReactiveMixIn[T]:
    """Methods for easily creating reactive values."""

    # No instance __dict__: an unknown attribute write on any wrapper raises
    # AttributeError instead of silently shadowing the reactive proxy.
    __slots__ = ()
    _IS_REACTIVE = True

    # Opt out of NumPy's ufunc machinery. Without this, `array + reactive` coerces the
    # reactive object into a 0-d object array and returns an object-dtype ndarray of
    # Computed values -- silently non-reactive -- because ndarray handles the operation
    # itself instead of returning NotImplemented. Setting this to None makes ndarray
    # defer, so Python falls back to the reflected operator here and builds a Computed.
    # The cost is that passing a reactive value straight to a ufunc (np.sin(reactive))
    # now raises TypeError instead of failing less clearly; use `reactive.rx.map(np.sin)`.
    __array_ufunc__ = None

    @property
    def value(self) -> T:
        """The current value of the reactive object."""
        ...

    def notify(self) -> None:
        """Notify all observers by calling their ``update`` method."""
        ...

    @overload
    def __getattr__(self, name: Literal["value", "_value"]) -> T: ...  # type: ignore

    @overload
    def __getattr__(self, name: str) -> Computed[Any]: ...

    def __getattr__(self, name: str) -> Union[T, Computed[Any]]:
        """Create a reactive value for retrieving an attribute from ``self.value``.

        Args:
            name: The name of the attribute to access.

        Returns:
            A reactive value for the attribute access.

        Raises:
            AttributeError: If the attribute doesn't exist.

        Note:
            Type inference is poor whenever `__getattr__` is used.

        Example:
            ```py
            >>> class Person:
            ...     def __init__(self, name):
            ...         self.name = name
            >>> s = Signal(Person("Alice"))
            >>> result = s.name
            >>> result.value
            'Alice'
            >>> s.value = Person("Bob")
            >>> result.value
            'Bob'

            ```
        """
        if name in {"value", "_value", "_impl"}:
            return super().__getattribute__(name)

        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        if hasattr(self.value, name):
            return _computed_call(getattr, self, name)

        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __call__[**P, R](self: "_ReactiveMixIn[Callable[P, R]]", *args: P.args, **kwargs: P.kwargs) -> Computed[R]:
        """Create a reactive value for calling `self.value(*args, **kwargs)`.

        Args:
            *args: Positional arguments to pass to the callable value.
            **kwargs: Keyword arguments to pass to the callable value.

        Returns:
            A reactive value for the function call.

        Raises:
            ValueError: If the value is not callable.

        Example:
            ```py
            >>> class Person:
            ...     def __init__(self, name):
            ...         self.name = name
            ...     def greet(self):
            ...         return f"Hi, I'm {self.name}!"
            >>> s = Signal(Person("Alice"))
            >>> result = s.greet()
            >>> result.value
            "Hi, I'm Alice!"
            >>> s.name = "Bob"
            >>> result.value
            "Hi, I'm Bob!"

            ```
        """
        if not callable(self.value):
            raise ValueError("Value is not callable.")

        def f(*args: Any, **kwargs: Any):
            return self.value(*args, **kwargs)

        return _computed_call(f, *args, **kwargs)

    def __abs__[R](self: _ReactiveOf[SupportsAbs[R]]) -> Computed[R]:
        """Return a reactive value for the absolute value of `self`.

        Returns:
            A reactive value for `abs(self.value)`.

        Example:
            ```py
            >>> s = Signal(-5)
            >>> result = abs(s)
            >>> result.value
            5
            >>> s.value = -10
            >>> result.value
            10

            ```
        """
        return _computed_call(abs, self)

    @property
    def rx(self) -> _ReactiveNamespace[T]:
        """Access reactive helper operations in a [namespace][signified._mixin._ReactiveNamespace]."""
        return _ReactiveNamespace(self)

    def __str__(self) -> str:
        """Return a string of the current value.

        Note:
            This is not reactive.

        Returns:
            A string representation of `self.value`.
        """
        return str(self.value)

    @overload
    def __round__(self: "_ReactiveMixIn[bool]") -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[bool]", ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[bool]", ndigits: int) -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[int]") -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[int]", ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[int]", ndigits: int) -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[float]") -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[float]", ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self: "_ReactiveMixIn[float]", ndigits: int) -> Computed[float]: ...
    @overload
    def __round__(self, ndigits: int | None = None) -> Computed[int] | Computed[float]: ...

    def __round__(self, ndigits: int | None = None) -> Computed[int] | Computed[float]:
        """Return a reactive value for the rounded value of self.

        Args:
            ndigits: Number of decimal places to round to.

        Returns:
            A reactive value for `round(self.value, ndigits)`.

        Example:
            ```py
            >>> s = Signal(3.14159)
            >>> result = round(s, 2)
            >>> result.value
            3.14
            >>> s.value = 2.71828
            >>> result.value
            2.72

            ```
        """
        return _computed_call(round, self, ndigits=ndigits)

    def __ceil__(self) -> Computed[int]:
        """Return a reactive value for the ceiling of `self`.

        Returns:
            A reactive value for `math.ceil(self.value)`.

        Example:
            ```py
            >>> from math import ceil
            >>> s = Signal(3.14)
            >>> result = ceil(s)
            >>> result.value
            4
            >>> s.value = 2.01
            >>> result.value
            3

            ```
        """
        return _computed_call(math.ceil, self)

    def __floor__(self) -> Computed[int]:
        """Return a reactive value for the floor of `self`.

        Returns:
            A reactive value for `math.floor(self.value)`.

        Example:
            ```py
            >>> from math import floor
            >>> s = Signal(3.99)
            >>> result = floor(s)
            >>> result.value
            3
            >>> s.value = 4.01
            >>> result.value
            4

            ```
        """
        return _computed_call(math.floor, self)

    def __invert__[R](self: _ReactiveOf[_SupportsInvert[R]]) -> Computed[R]:
        """Return a reactive value for the bitwise inversion of `self`.

        Returns:
            A reactive value for `~self.value`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = ~s
            >>> result.value
            -6
            >>> s.value = -3
            >>> result.value
            2

            ```
        """
        return _computed_call(operator.inv, self)

    def __neg__[R](self: _ReactiveOf[_SupportsNeg[R]]) -> Computed[R]:
        """Return a reactive value for the negation of `self`.

        Returns:
            A reactive value for `-self.value`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = -s
            >>> result.value
            -5
            >>> s.value = -3
            >>> result.value
            3

            ```
        """
        return _computed_call(operator.neg, self)

    def __pos__[R](self: _ReactiveOf[_SupportsPos[R]]) -> Computed[R]:
        """Return a reactive value for the positive of self.

        Returns:
            A reactive value for `+self.value`.

        Example:
            ```py
            >>> s = Signal(-5)
            >>> result = +s
            >>> result.value
            -5
            >>> s.value = 3
            >>> result.value
            3

            ```
        """
        return _computed_call(operator.pos, self)

    def __trunc__[R](self: _ReactiveOf[_SupportsTrunc[R]]) -> Computed[R]:
        """Return a reactive value for the truncated value of `self`.

        Returns:
            A reactive value for `math.trunc(self.value)`.

        Example:
            ```py
            >>> from math import trunc
            >>> s = Signal(3.99)
            >>> result = trunc(s)
            >>> result.value
            3
            >>> s.value = -4.01
            >>> result.value
            -4

            ```
        """
        return _computed_call(math.trunc, self)

    @overload
    def __add__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __add__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __add__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __add__[Y, R](self: "_ReactiveOf[_SupportsAdd[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __add__(self, other: Any) -> Computed[Any]: ...

    def __add__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the sum of `self` and `other`.

        Args:
            other: The value to add.

        Returns:
            A reactive value for `self.value + other.value`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = s + 3
            >>> result.value
            8
            >>> s.value = 10
            >>> result.value
            13

            ```
        """
        return _computed_call(operator.add, self, other)

    @overload
    def __and__[N: (bool, int)](self: "_ReactiveMixIn[bool]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __and__(self: "_ReactiveMixIn[int]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __and__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __and__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the bitwise AND of self and other.

        Args:
            other: The value to AND with.

        Returns:
            A reactive value for `self.value & other.value`.

        Example:
            ```py
            >>> s = Signal(True)
            >>> result = s & False
            >>> result.value
            False
            >>> s.value = True
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.and_, self, other)

    @overload
    def __divmod__[N: (int, float)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[tuple[N, N]]: ...

    @overload
    def __divmod__(self: "_ReactiveMixIn[float]", other: _FloatLike) -> Computed[tuple[float, float]]: ...

    @overload
    def __divmod__[Y, R](self: "_ReactiveOf[_SupportsDivmod[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __divmod__(self, other: Any) -> Computed[Any]: ...

    def __divmod__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the divmod of `self` and other.

        Args:
            other: The value to use as the divisor.

        Returns:
            A reactive value for `divmod(self.value, other)`.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = divmod(s, 3)
            >>> result.value
            (3, 1)
            >>> s.value = 20
            >>> result.value
            (6, 2)

            ```
        """
        return _computed_call(divmod, self, other)

    @overload
    def __floordiv__[N: (int, float)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __floordiv__(self: "_ReactiveMixIn[float]", other: _FloatLike) -> Computed[float]: ...

    @overload
    def __floordiv__[Y, R](self: "_ReactiveOf[_SupportsFloordiv[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __floordiv__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __floordiv__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the floor division of `self` by other.

        Args:
            other: The value to use as the divisor.

        Returns:
            A reactive value for self.value // other.value.

        Example:
            ```py
            >>> s = Signal(20)
            >>> result = s // 3
            >>> result.value
            6
            >>> s.value = 25
            >>> result.value
            8

            ```
        """
        return _computed_call(operator.floordiv, self, other)

    def __ge__(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `self` is greater than or equal to other.

        Args:
            other: The value to compare against.

        Returns:
            A reactive value for self.value >= other.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = s >= 5
            >>> result.value
            True
            >>> s.value = 3
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.ge, self, other)

    def __gt__(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `self` is greater than other.

        Args:
            other: The value to compare against.

        Returns:
            A reactive value for self.value > other.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = s > 5
            >>> result.value
            True
            >>> s.value = 3
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.gt, self, other)

    def __le__(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `self` is less than or equal to `other`.

        Args:
            other: The value to compare against.

        Returns:
            A reactive value for `self.value <= other`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = s <= 5
            >>> result.value
            True
            >>> s.value = 6
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.le, self, other)

    def __lt__(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `self` is less than `other`.

        Args:
            other: The value to compare against.

        Returns:
            A reactive value for `self.value < other`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = s < 10
            >>> result.value
            True
            >>> s.value = 15
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.lt, self, other)

    @overload
    def __lshift__(self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __lshift__[Y, R](self: "_ReactiveOf[_SupportsLshift[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __lshift__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __lshift__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` left-shifted by `other`.

        Args:
            other: The number of positions to shift.

        Returns:
            A reactive value for `self.value << other.value`.

        Example:
            ```py
            >>> s = Signal(8)
            >>> result = s << 2
            >>> result.value
            32
            >>> s.value = 3
            >>> result.value
            12

            ```
        """
        return _computed_call(operator.lshift, self, other)

    @overload
    def __matmul__[Y, R](self: "_ReactiveOf[_SupportsMatmul[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __matmul__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __matmul__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the matrix multiplication of `self` and `other`.

        Args:
            other: The value to multiply with.

        Returns:
            A reactive value for `self.value @ other.value`.

        Example:
            ```py
            >>> import numpy as np
            >>> s = Signal(np.array([1, 2]))
            >>> result = s @ np.array([[1, 2], [3, 4]])
            >>> result.value
            array([ 7, 10])
            >>> s.value = np.array([2, 3])
            >>> result.value
            array([11, 16])

            ```
        """
        return _computed_call(operator.matmul, self, other)

    @overload
    def __mod__[N: (int, float)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __mod__(self: "_ReactiveMixIn[float]", other: _FloatLike) -> Computed[float]: ...

    @overload
    def __mod__[Y, R](self: "_ReactiveOf[_SupportsMod[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __mod__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __mod__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` modulo `other`.

        Args:
            other: The divisor.

        Returns:
            A reactive value for `self.value % other.value`.

        Example:
            ```py
            >>> s = Signal(17)
            >>> result = s % 5
            >>> result.value
            2
            >>> s.value = 23
            >>> result.value
            3

            ```
        """
        return _computed_call(operator.mod, self, other)

    @overload
    def __mul__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __mul__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __mul__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __mul__(self: "_ReactiveMixIn[str]", other: HasValue[int]) -> Computed[str]: ...

    @overload
    def __mul__[V](self: "_ReactiveMixIn[list[V]]", other: HasValue[int]) -> Computed[list[V]]: ...

    @overload
    def __mul__[Y, R](self: "_ReactiveOf[_SupportsMul[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __mul__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __mul__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the product of `self` and `other`.

        Args:
            other: The value to multiply with.

        Returns:
            A reactive value for `self.value * other.value`.

        Example:
            ```py
            >>> s = Signal(4)
            >>> result = s * 3
            >>> result.value
            12
            >>> s.value = 5
            >>> result.value
            15

            ```
        """
        return _computed_call(operator.mul, self, other)

    @overload
    def __or__[N: (bool, int)](self: "_ReactiveMixIn[bool]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __or__(self: "_ReactiveMixIn[int]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __or__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __or__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the bitwise OR of `self` and `other`.

        Args:
            other: The value to OR with.

        Returns:
            A reactive value for `self.value or other.value`.

        Example:
            ```py
            >>> s = Signal(False)
            >>> result = s | True
            >>> result.value
            True
            >>> s.value = True
            >>> result.value
            True

            ```
        """
        return _computed_call(operator.or_, self, other)

    @overload
    def __rshift__(self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __rshift__[Y, R](self: "_ReactiveOf[_SupportsRshift[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __rshift__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rshift__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` right-shifted by `other`.

        Args:
            other: The number of positions to shift.

        Returns:
            A reactive value for `self.value >> other.value`.

        Example:
            ```py
            >>> s = Signal(32)
            >>> result = s >> 2
            >>> result.value
            8
            >>> s.value = 24
            >>> result.value
            6

            ```
        """
        return _computed_call(operator.rshift, self, other)

    @overload
    def __pow__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __pow__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __pow__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __pow__[Y, R](self: "_ReactiveOf[_SupportsPow[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __pow__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __pow__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` raised to the power of `other`.

        Args:
            other: The exponent.

        Returns:
            A reactive value for `self.value ** other.value`.

        Example:
            ```py
            >>> s = Signal(2)
            >>> result = s ** 3
            >>> result.value
            8
            >>> s.value = 3
            >>> result.value
            27

            ```
        """
        return _computed_call(operator.pow, self, other)

    @overload
    def __sub__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __sub__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __sub__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __sub__[D: date](self: "_ReactiveMixIn[D]", other: HasValue[timedelta]) -> Computed[D]: ...

    @overload
    def __sub__[D: date](self: "_ReactiveMixIn[D]", other: HasValue[D]) -> Computed[timedelta]: ...

    @overload
    def __sub__[Y, R](self: "_ReactiveOf[_SupportsSub[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __sub__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __sub__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the difference of `self` and `other`.

        Args:
            other: The value to subtract.

        Returns:
            A reactive value for `self.value - other.value`.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = s - 3
            >>> result.value
            7
            >>> s.value = 15
            >>> result.value
            12

            ```
        """
        return _computed_call(operator.sub, self, other)

    @overload
    def __truediv__[N: (float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool] | _ReactiveMixIn[float]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __truediv__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __truediv__[Y, R](self: "_ReactiveOf[_SupportsTruediv[Y, R]]", other: HasValue[Y]) -> Computed[R]: ...

    @overload
    def __truediv__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __truediv__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` divided by `other`.

        Args:
            other: The value to use as the divisor.

        Returns:
            A reactive value for `self.value / other.value`.

        Example:
            ```py
            >>> s = Signal(20)
            >>> result = s / 4
            >>> result.value
            5.0
            >>> s.value = 30
            >>> result.value
            7.5

            ```
        """
        return _computed_call(operator.truediv, self, other)

    @overload
    def __xor__[N: (bool, int)](self: "_ReactiveMixIn[bool]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __xor__(self: "_ReactiveMixIn[int]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __xor__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __xor__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the bitwise XOR of `self` and `other`.

        Args:
            other: The value to XOR with.

        Returns:
            A reactive value for `self.value ^ other.value`.

        Example:
            ```py
            >>> s = Signal(True)
            >>> result = s ^ False
            >>> result.value
            True
            >>> s.value = False
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.xor, self, other)

    @overload
    def __radd__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __radd__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __radd__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __radd__[D: date](self: "_ReactiveMixIn[D]", other: HasValue[timedelta]) -> Computed[D]: ...

    @overload
    def __radd__[R](self, other: HasValue[_SupportsAdd[T, R]]) -> Computed[R]: ...

    @overload
    def __radd__(self, other: Any) -> Computed[Any]: ...

    def __radd__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the sum of `self` and `other`.

        Args:
            other: The value to add.

        Returns:
            A reactive value for `self.value + other.value`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = 3 + s
            >>> result.value
            8
            >>> s.value = 10
            >>> result.value
            13

            ```
        """
        return _computed_call(operator.add, other, self)

    @overload
    def __rand__[N: (bool, int)](self: "_ReactiveMixIn[bool]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __rand__(self: "_ReactiveMixIn[int]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __rand__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rand__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the bitwise AND of `self` and `other`.

        Args:
            other: The value to AND with.

        Returns:
            A reactive value for `self.value and other.value`.

        Example:
            ```py
            >>> s = Signal(True)
            >>> result = False & s
            >>> result.value
            False
            >>> s.value = True
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.and_, other, self)

    @overload
    def __rdivmod__[N: (int, float)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[tuple[N, N]]: ...

    @overload
    def __rdivmod__(self: "_ReactiveMixIn[float]", other: _FloatLike) -> Computed[tuple[float, float]]: ...

    @overload
    def __rdivmod__[R](self, other: HasValue[_SupportsDivmod[T, R]]) -> Computed[R]: ...

    @overload
    def __rdivmod__(self, other: Any) -> Computed[Any]: ...

    def __rdivmod__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the divmod of `self` and `other`.

        Args:
            other: The value to use as the numerator.

        Returns:
            A reactive value for `divmod(other, self.value)`.

        Example:
            ```py
            >>> s = Signal(3)
            >>> result = divmod(10, s)
            >>> result.value
            (3, 1)
            >>> s.value = 4
            >>> result.value
            (2, 2)

            ```
        """
        return _computed_call(divmod, other, self)

    @overload
    def __rfloordiv__[N: (int, float)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __rfloordiv__(self: "_ReactiveMixIn[float]", other: _FloatLike) -> Computed[float]: ...

    @overload
    def __rfloordiv__[R](self, other: HasValue[_SupportsFloordiv[T, R]]) -> Computed[R]: ...

    @overload
    def __rfloordiv__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rfloordiv__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the floor division of `other` by `self`.

        Args:
            other: The value to use as the numerator.

        Returns:
            A reactive value for `other.value // self.value`.

        Example:
            ```py
            >>> s = Signal(3)
            >>> result = 10 // s
            >>> result.value
            3
            >>> s.value = 4
            >>> result.value
            2

            ```
        """
        return _computed_call(operator.floordiv, other, self)

    @overload
    def __rlshift__(self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __rlshift__[R](self, other: HasValue[_SupportsLshift[T, R]]) -> Computed[R]: ...

    @overload
    def __rlshift__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rlshift__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `other` left-shifted by `self`.

        Args:
            other: The value to shift.

        Returns:
            A reactive value for `other.value << self.value`.

        Example:
            ```py
            >>> s = Signal(2)
            >>> result = 1 << s
            >>> result.value
            4
            >>> s.value = 5
            >>> result.value
            32

            ```
        """
        return _computed_call(operator.lshift, other, self)

    @overload
    def __rmatmul__[R](self, other: HasValue[_SupportsMatmul[T, R]]) -> Computed[R]: ...

    @overload
    def __rmatmul__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rmatmul__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the matrix multiplication of `other` and `self`.

        Note:
            NumPy arrays on the left defer to this method because reactive values
            opt out of NumPy's ufunc dispatch. The result is a single `Computed`.

        Args:
            other: The value to multiply with.

        Returns:
            A reactive value for `other.value @ self.value`.

        Example:
            ```py
            >>> class Row:
            ...     def __init__(self, values):
            ...         self.values = values
            ...     def __matmul__(self, other):
            ...         if not isinstance(other, Row):
            ...             return NotImplemented
            ...         return sum(a * b for a, b in zip(self.values, other.values))
            >>> s = Signal(Row([3, 4]))
            >>> result = Row([1, 2]) @ s
            >>> result.value
            11
            >>> s.value = Row([1, 1])
            >>> result.value
            3

            ```
        """
        return _computed_call(operator.matmul, other, self)

    @overload
    def __rmod__[N: (int, float)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __rmod__(self: "_ReactiveMixIn[float]", other: _FloatLike) -> Computed[float]: ...

    @overload
    def __rmod__[R](self, other: HasValue[_SupportsMod[T, R]]) -> Computed[R]: ...

    @overload
    def __rmod__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rmod__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `other` modulo `self`.

        Args:
            other: The dividend.

        Returns:
            A reactive value for `other.value % self.value`.

        Example:
            ```py
            >>> s = Signal(3)
            >>> result = 10 % s
            >>> result.value
            1
            >>> s.value = 4
            >>> result.value
            2

            ```
        """
        return _computed_call(operator.mod, other, self)

    @overload
    def __rmul__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __rmul__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __rmul__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __rmul__(self: "_ReactiveMixIn[str]", other: HasValue[int]) -> Computed[str]: ...

    @overload
    def __rmul__[V](self: "_ReactiveMixIn[list[V]]", other: HasValue[int]) -> Computed[list[V]]: ...

    @overload
    def __rmul__[R](self, other: HasValue[_SupportsMul[T, R]]) -> Computed[R]: ...

    @overload
    def __rmul__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rmul__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the product of `self` and `other`.

        Args:
            other: The value to multiply with.

        Returns:
            A reactive value for `self.value * other.value`.

        Example:
            ```py
            >>> s = Signal(4)
            >>> result = 3 * s
            >>> result.value
            12
            >>> s.value = 5
            >>> result.value
            15

            ```
        """
        return _computed_call(operator.mul, other, self)

    @overload
    def __ror__[N: (bool, int)](self: "_ReactiveMixIn[bool]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __ror__(self: "_ReactiveMixIn[int]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __ror__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __ror__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the bitwise OR of `self` and `other`.

        Args:
            other: The value to OR with.

        Returns:
            A reactive value for `self.value or other.value`.

        Example:
            ```py
            >>> s = Signal(False)
            >>> result = True | s
            >>> result.value
            True
            >>> s.value = True
            >>> result.value
            True

            ```
        """
        return _computed_call(operator.or_, other, self)

    @overload
    def __rpow__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __rpow__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __rpow__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __rpow__[R](self, other: HasValue[_SupportsPow[T, R]]) -> Computed[R]: ...

    @overload
    def __rpow__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rpow__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` raised to the power of `other`.

        Args:
            other: The base.

        Returns:
            A reactive value for `self.value ** other.value`.

        Example:
            ```py
            >>> s = Signal(2)
            >>> result = 3 ** s
            >>> result.value
            9
            >>> s.value = 3
            >>> result.value
            27

            ```
        """
        return _computed_call(operator.pow, other, self)

    @overload
    def __rrshift__(self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __rrshift__[R](self, other: HasValue[_SupportsRshift[T, R]]) -> Computed[R]: ...

    @overload
    def __rrshift__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rrshift__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `other` right-shifted by `self`.

        Args:
            other: The value to shift.

        Returns:
            A reactive value for `other.value >> self.value`.

        Example:
            ```py
            >>> s = Signal(2)
            >>> result = 32 >> s
            >>> result.value
            8
            >>> s.value = 4
            >>> result.value
            2

            ```
        """
        return _computed_call(operator.rshift, other, self)

    @overload
    def __rsub__[N: (int, float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __rsub__[N: (float, complex)](self: "_ReactiveMixIn[float]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __rsub__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __rsub__[R](self, other: HasValue[_SupportsSub[T, R]]) -> Computed[R]: ...

    @overload
    def __rsub__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rsub__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the difference of `self` and `other`.

        Args:
            other: The value to subtract from.

        Returns:
            A reactive value for `other.value - self.value`.

        Example:
            ```py
            >>> s = Signal(10)
            >>> result = 15 - s
            >>> result.value
            5
            >>> s.value = 15
            >>> result.value
            0

            ```
        """
        return _computed_call(operator.sub, other, self)

    @overload
    def __rtruediv__[N: (float, complex)](
        self: "_ReactiveMixIn[int] | _ReactiveMixIn[bool] | _ReactiveMixIn[float]", other: HasValue[N]
    ) -> Computed[N]: ...

    @overload
    def __rtruediv__(self: "_ReactiveMixIn[complex]", other: _ComplexLike) -> Computed[complex]: ...

    @overload
    def __rtruediv__[R](self, other: HasValue[_SupportsTruediv[T, R]]) -> Computed[R]: ...

    @overload
    def __rtruediv__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rtruediv__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for `self` divided by `other`.

        Args:
            other: The value to use as the divisor.

        Returns:
            A reactive value for `self.value / other.value`.

        Example:
            ```py
            >>> s = Signal(2)
            >>> result = 30 / s
            >>> result.value
            15.0
            >>> s.value = 3
            >>> result.value
            10.0

            ```
        """
        return _computed_call(operator.truediv, other, self)

    @overload
    def __rxor__[N: (bool, int)](self: "_ReactiveMixIn[bool]", other: HasValue[N]) -> Computed[N]: ...

    @overload
    def __rxor__(self: "_ReactiveMixIn[int]", other: _IntLike) -> Computed[int]: ...

    @overload
    def __rxor__[Y](self, other: HasValue[Y]) -> Computed[T | Y]: ...

    def __rxor__(self, other: Any) -> Computed[Any]:
        """Return a reactive value for the bitwise XOR of `self` and `other`.

        Args:
            other: The value to XOR with.

        Returns:
            A reactive value for `self.value ^ other.value`.

        Example:
            ```py
            >>> s = Signal(True)
            >>> result = False ^ s
            >>> result.value
            True
            >>> s.value = False
            >>> result.value
            False

            ```
        """
        return _computed_call(operator.xor, other, self)

    @overload
    def __getitem__[V](self: "_ReactiveMixIn[list[V]]", key: HasValue[slice]) -> Computed[list[V]]: ...

    @overload
    def __getitem__[V](self: "_ReactiveMixIn[tuple[V, ...]]", key: HasValue[slice]) -> Computed[tuple[V, ...]]: ...

    @overload
    def __getitem__(self: "_ReactiveMixIn[str]", key: HasValue[slice]) -> Computed[str]: ...

    @overload
    def __getitem__[V](self: "_ReactiveMixIn[list[V]]", key: _IndexLike) -> Computed[V]: ...

    @overload
    def __getitem__[V](self: "_ReactiveMixIn[tuple[V, ...]]", key: _IndexLike) -> Computed[V]: ...

    @overload
    def __getitem__(self: "_ReactiveMixIn[str]", key: _IndexLike) -> Computed[str]: ...

    @overload
    def __getitem__[K, V](self: "_ReactiveMixIn[dict[K, V]]", key: HasValue[K]) -> Computed[V]: ...

    @overload
    def __getitem__[K, V](self: "_ReactiveOf[_SupportsGetItem[K, V]]", key: HasValue[K]) -> Computed[V]: ...

    @overload
    def __getitem__(self, key: Any) -> Computed[Any]: ...

    def __getitem__(self, key: Any) -> Computed[Any]:
        """Return a reactive value for the item or slice of `self`.

        Args:
            key: The index or slice to retrieve.

        Returns:
            A reactive value for `self.value[key]`.

        Example:
            ```py
            >>> s = Signal([1, 2, 3, 4, 5])
            >>> result = s[2]
            >>> result.value
            3
            >>> s.value = [10, 20, 30, 40, 50]
            >>> result.value
            30

            ```
        """
        return _computed_call(operator.getitem, self, key)

    def _bump_version(self) -> int:
        """Increment the local version counter and the shared global version clock."""
        object.__setattr__(self, "_version", self._version + 1)
        return _bump_global_version()


# Loaded after _ReactiveMixIn is defined to avoid import cycles.
from ._functions import _computed_call  # noqa: E402
from ._reactive import Effect, _bump_global_version  # noqa: E402
