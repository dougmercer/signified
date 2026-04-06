"""Core reactive programming functionality."""

from __future__ import annotations

import math
import operator
from functools import cache
from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol, SupportsIndex, Union, overload

from ._types import HasValue

if TYPE_CHECKING:
    from ._reactive import Computed

__all__ = ["_ReactiveMixIn"]


_PLAIN_COMPUTED_ARG_TYPES = {int, float, str, bool, bytes, complex, type(None)}


class _SupportsAdd[OtherT, ResultT](Protocol):
    def __add__(self, other: OtherT, /) -> ResultT: ...


class _SupportsGetItem[KeyT, ValueT](Protocol):
    def __getitem__(self, key: KeyT, /) -> ValueT: ...


class _ReactiveSupportsAdd[OtherT, ResultT](Protocol):
    @property
    def value(self) -> _SupportsAdd[OtherT, ResultT]: ...


class _ReactiveSupportsGetItem[KeyT, ValueT](Protocol):
    @property
    def value(self) -> _SupportsGetItem[KeyT, ValueT]: ...


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
        return computed(fn)(self._source)

    def effect(self, fn: Callable[[T], None]) -> "Effect":
        """Eagerly run `fn` for side effects whenever the source changes.

        `fn` is called immediately on creation and again on every subsequent
        change — without requiring the caller to read `.value`.

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

    def peek(self, fn: Callable[[T], Any]) -> Computed[T]:
        """Run `fn` for side effects and pass through the original value.

        `fn` only executes when the returned [Computed][signified.Computed] is read, not on every
        upstream change. Intermediate values are skipped if the source changes
        multiple times between reads.

        Warning:
            The returned [Computed][signified.Computed] must be kept alive by the caller.
            Observers are held as weak references, so if nothing holds a strong
            reference to the returned value, it will be garbage-collected and
            `fn` will silently stop running.

            `fn` fires on each explicit `.value` read — **not** on creation and
            not on upstream changes alone. If the returned object is
            garbage-collected before any `.value` read, `fn` never fires at all:

            ```python
            s.rx.peek(print)  # GC'd immediately — print never called
            ```

            For eager side effects, use the `effect` method or [Effect][signified.Effect] directly.

        Args:
            fn: Side-effect callback that receives the current source value.

        Returns:
            A reactive value that always equals `source.value`.

        Example:
            ```py
            >>> seen = []
            >>> s = Signal(1)
            >>> passthrough = s.rx.peek(lambda x: seen.append(x))
            >>> passthrough.value
            1
            >>> s.value = 3
            >>> passthrough.value
            3
            >>> seen
            [1, 3]

            ```
        """

        @computed
        def _peek(value: T) -> T:
            fn(value)
            return value

        return _peek(self._source)

    def len(self) -> Computed[int]:
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
        return computed(len)(self._source)

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
        return computed(operator.is_)(self._source, other)

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
        return computed(operator.is_not)(self._source, other)

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
        return computed(operator.contains)(container, self._source)

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
        return computed(operator.contains)(self._source, other)

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
        return computed(operator.eq)(self._source, other)

    def where[A, B](self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]:
        """Return a reactive value for ``a`` if ``source`` is truthy, else ``b``.

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

        @computed
        def ternary(a: A, b: B, condition: Any) -> A | B:
            return a if condition else b

        return ternary(a, b, self._source)

    def as_bool(self) -> Computed[bool]:
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
        return computed(bool)(self._source)


class _ReactiveMixIn[T]:
    """Methods for easily creating reactive values."""

    _IS_REACTIVE = True

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
            return self._attr_computed(name)

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

        return self._invoke_value_computed(*args, **kwargs)

    @overload
    def __abs__(self: "_ReactiveMixIn[complex]") -> Computed[float]: ...

    @overload
    def __abs__(self: "_ReactiveMixIn[bool]") -> Computed[int]: ...

    @overload
    def __abs__(self) -> Computed[T]: ...

    def __abs__(self) -> Computed[T] | Computed[float] | Computed[int]:
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
        return self._unary_computed(self, abs)

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
        return self._apply_computed(round, self, ndigits=ndigits)

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
        return self._unary_computed(self, math.ceil)

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
        return self._unary_computed(self, math.floor)

    @overload
    def __invert__(self: "_ReactiveMixIn[bool]") -> Computed[int]: ...

    @overload
    def __invert__(self) -> Computed[T]: ...

    def __invert__(self) -> Computed[T] | Computed[int]:
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
        return self._unary_computed(self, operator.inv)

    @overload
    def __neg__(self: "_ReactiveMixIn[bool]") -> Computed[int]: ...

    @overload
    def __neg__(self) -> Computed[T]: ...

    def __neg__(self) -> Computed[T] | Computed[int]:
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
        return self._unary_computed(self, operator.neg)

    @overload
    def __pos__(self: "_ReactiveMixIn[bool]") -> Computed[int]: ...

    @overload
    def __pos__(self) -> Computed[T]: ...

    def __pos__(self) -> Computed[T] | Computed[int]:
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
        return self._unary_computed(self, operator.pos)

    @overload
    def __trunc__(self: "_ReactiveMixIn[bool]") -> Computed[int]: ...

    @overload
    def __trunc__(self: "_ReactiveMixIn[int]") -> Computed[int]: ...

    @overload
    def __trunc__(self: "_ReactiveMixIn[float]") -> Computed[int]: ...

    @overload
    def __trunc__(self) -> Computed[T]: ...

    def __trunc__(self) -> Computed[T] | Computed[int]:
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
        return self._unary_computed(self, math.trunc)

    @overload
    def __add__(self: "_ReactiveMixIn[float]", other: HasValue[int] | HasValue[float]) -> Computed[float]: ...

    @overload
    def __add__(self: "_ReactiveMixIn[int]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __add__[Y, R](self: "_ReactiveSupportsAdd[Y, R]", other: HasValue[Y]) -> Computed[R]: ...

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
        return self._binary_computed(self, other, operator.add)

    def __and__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.and_)

    @overload
    def __divmod__(self: "_ReactiveMixIn[int]", other: HasValue[int]) -> Computed[tuple[int, int]]: ...

    @overload
    def __divmod__(
        self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]
    ) -> Computed[tuple[int, int]]: ...

    @overload
    def __divmod__(self, other: Any) -> Computed[tuple[float, float]]: ...

    def __divmod__(self, other: Any) -> Computed[tuple[int, int]] | Computed[tuple[float, float]]:
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
        return self._binary_computed(self, other, divmod)

    @overload
    def __floordiv__(self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return self._binary_computed(self, other, operator.floordiv)

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
        return self._binary_computed(self, other, operator.ge)

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
        return self._binary_computed(self, other, operator.gt)

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
        return self._binary_computed(self, other, operator.le)

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
        return self._binary_computed(self, other, operator.lt)

    def __lshift__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.lshift)

    def __matmul__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.matmul)

    @overload
    def __mod__(self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return self._binary_computed(self, other, operator.mod)

    @overload
    def __mul__(self: "_ReactiveMixIn[str]", other: HasValue[int]) -> Computed[str]: ...

    @overload
    def __mul__[V](self: "_ReactiveMixIn[list[V]]", other: HasValue[int]) -> Computed[list[V]]: ...

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
        return self._binary_computed(self, other, operator.mul)

    def __ne__(self, other: Any) -> Computed[bool]:  # type: ignore[override]
        """Return a reactive value for whether `self` is not equal to `other`.

        Args:
            other: The value to compare against.

        Returns:
            A reactive value for `self.value != other`.

        Example:
            ```py
            >>> s = Signal(5)
            >>> result = s != 5
            >>> result.value
            False
            >>> s.value = 6
            >>> result.value
            True

            ```
        """
        return self._binary_computed(self, other, operator.ne)

    def __or__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.or_)

    def __rshift__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.rshift)

    @overload
    def __pow__(self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return self._binary_computed(self, other, operator.pow)

    def __sub__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.sub)

    @overload
    def __truediv__(self: "_ReactiveMixIn[int]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __truediv__(self: "_ReactiveMixIn[int]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __truediv__(self: "_ReactiveMixIn[float]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __truediv__(self: "_ReactiveMixIn[float]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __truediv__(
        self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int] | HasValue[float]
    ) -> Computed[float]: ...

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
        return self._binary_computed(self, other, operator.truediv)

    def __xor__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(self, other, operator.xor)

    @overload
    def __radd__(self: "_ReactiveMixIn[float]", other: HasValue[int] | HasValue[float]) -> Computed[float]: ...

    @overload
    def __radd__[R](self: "_ReactiveMixIn[T]", other: HasValue[_SupportsAdd[T, R]]) -> Computed[R]: ...

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
        return self._binary_computed(other, self, operator.add)

    def __rand__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(other, self, operator.and_)

    @overload
    def __rdivmod__(self: "_ReactiveMixIn[int]", other: HasValue[int]) -> Computed[tuple[int, int]]: ...

    @overload
    def __rdivmod__(self: "_ReactiveMixIn[bool]", other: HasValue[int]) -> Computed[tuple[int, int]]: ...

    @overload
    def __rdivmod__(self: "_ReactiveMixIn[bool]", other: HasValue[bool]) -> Computed[tuple[int, int]]: ...

    @overload
    def __rdivmod__(self, other: Any) -> Computed[tuple[float, float]]: ...

    def __rdivmod__(self, other: Any) -> Computed[tuple[int, int]] | Computed[tuple[float, float]]:
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
        return self._binary_computed(other, self, divmod)

    @overload
    def __rfloordiv__(self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return self._binary_computed(other, self, operator.floordiv)

    @overload
    def __rmod__(self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return self._binary_computed(other, self, operator.mod)

    @overload
    def __rmul__(self: "_ReactiveMixIn[str]", other: HasValue[int]) -> Computed[str]: ...

    @overload
    def __rmul__[V](self: "_ReactiveMixIn[list[V]]", other: HasValue[int]) -> Computed[list[V]]: ...

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
        return self._binary_computed(other, self, operator.mul)

    def __ror__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(other, self, operator.or_)

    @overload
    def __rpow__(self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return self._binary_computed(other, self, operator.pow)

    def __rsub__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(other, self, operator.sub)

    @overload
    def __rtruediv__(self: "_ReactiveMixIn[int]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __rtruediv__(self: "_ReactiveMixIn[int]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __rtruediv__(self: "_ReactiveMixIn[float]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __rtruediv__(self: "_ReactiveMixIn[float]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __rtruediv__(
        self: "_ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int] | HasValue[float]
    ) -> Computed[float]: ...

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
        return self._binary_computed(other, self, operator.truediv)

    def __rxor__[Y](self, other: HasValue[Y]) -> Computed[T | Y]:
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
        return self._binary_computed(other, self, operator.xor)

    @overload
    def __getitem__[V](self: "_ReactiveMixIn[list[V]]", key: slice) -> Computed[list[V]]: ...

    @overload
    def __getitem__[V](self: "_ReactiveMixIn[tuple[V, ...]]", key: slice) -> Computed[tuple[V, ...]]: ...

    @overload
    def __getitem__(self: "_ReactiveMixIn[str]", key: slice) -> Computed[str]: ...

    @overload
    def __getitem__[V](
        self: "_ReactiveMixIn[list[V]]", key: HasValue[SupportsIndex] | HasValue[int]
    ) -> Computed[V]: ...

    @overload
    def __getitem__[V](
        self: "_ReactiveMixIn[tuple[V, ...]]", key: HasValue[SupportsIndex] | HasValue[int]
    ) -> Computed[V]: ...

    @overload
    def __getitem__(self: "_ReactiveMixIn[str]", key: HasValue[SupportsIndex] | HasValue[int]) -> Computed[str]: ...

    @overload
    def __getitem__[K, V](self: "_ReactiveMixIn[dict[K, V]]", key: HasValue[K]) -> Computed[V]: ...

    @overload
    def __getitem__[K, V](self: "_ReactiveSupportsGetItem[K, V]", key: HasValue[K]) -> Computed[V]: ...

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
        return self._binary_computed(self, key, operator.getitem)

    @staticmethod
    def _identity_arg(value: Any) -> Any:
        return value

    @staticmethod
    def _value_arg(value: HasValue[Any]) -> Any:
        return value.value

    @staticmethod
    def _resolver_for(value: Any) -> Callable[[Any], Any]:
        if _is_reactive_value(value):
            return _ReactiveMixIn._value_arg
        if type(value) in _PLAIN_COMPUTED_ARG_TYPES:
            return _ReactiveMixIn._identity_arg
        return deep_unref

    @staticmethod
    def _apply_computed(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Computed[Any]:
        """Create a computed with faster direct-value resolvers for reactive args."""
        if not kwargs:
            if not args:
                return Computed(func)
            if len(args) == 1:
                arg = args[0]
                resolve_arg = _ReactiveMixIn._resolver_for(arg)
                return Computed(lambda: func(resolve_arg(arg)))
            if len(args) == 2:
                left, right = args
                resolve_left = _ReactiveMixIn._resolver_for(left)
                resolve_right = _ReactiveMixIn._resolver_for(right)
                return Computed(lambda: func(resolve_left(left), resolve_right(right)))

        arg_resolvers = tuple(_ReactiveMixIn._resolver_for(arg) for arg in args)
        kw_resolvers = {key: _ReactiveMixIn._resolver_for(value) for key, value in kwargs.items()}

        def compute_func() -> Any:
            resolved_args = tuple(resolver(arg) for resolver, arg in zip(arg_resolvers, args, strict=False))
            resolved_kwargs = {key: kw_resolvers[key](value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func)

    @staticmethod
    def _unary_computed(value: HasValue[Any], op: Callable[[Any], Any]) -> Computed[Any]:
        resolve_value = _ReactiveMixIn._resolver_for(value)
        return Computed(lambda: op(resolve_value(value)))

    @staticmethod
    def _binary_computed(left: HasValue[Any], right: HasValue[Any], op: Callable[[Any, Any], Any]) -> Computed[Any]:
        """Create a binary computed with direct-value reactive resolution."""
        resolve_left = _ReactiveMixIn._resolver_for(left)
        resolve_right = _ReactiveMixIn._resolver_for(right)
        return Computed(lambda: op(resolve_left(left), resolve_right(right)))

    def _attr_computed(self, name: str) -> Computed[Any]:
        return Computed(lambda: getattr(self.value, name))

    def _invoke_value_computed(self, *args: Any, **kwargs: Any) -> Computed[Any]:
        arg_resolvers = tuple(self._resolver_for(arg) for arg in args)
        kw_resolvers = {key: self._resolver_for(value) for key, value in kwargs.items()}

        def compute_func() -> Any:
            resolved_args = tuple(resolver(arg) for resolver, arg in zip(arg_resolvers, args, strict=False))
            resolved_kwargs = {key: kw_resolvers[key](value) for key, value in kwargs.items()}
            return self.value(*resolved_args, **resolved_kwargs)

        return Computed(compute_func)

    @classmethod
    @cache
    def _own_attr_names(cls) -> frozenset[str]:
        return frozenset(name for base in cls.__mro__ for name in base.__dict__)

    @classmethod
    def _is_own_attr(cls, name: str) -> bool:
        """Return whether `name` is defined on this wrapper type or one of its bases."""
        return name in cls._own_attr_names()

    def _bump_version(self) -> int:
        """Increment the local version counter and the shared global version clock."""
        object.__setattr__(self, "_version", self._version + 1)
        return _bump_global_version()

    def __setattr__(self, name: str, value: Any) -> None:
        """Assign `name` on the wrapper or forward it to the wrapped value.

        Private attributes and names owned by the wrapper type are assigned on the
        wrapper itself. Other names are forwarded to the wrapped value when that
        object already defines the attribute, then observers are notified so
        dependents recompute.

        This allows `signal.name = "Bob"` to update the wrapped object while still
        preserving the wrapper's own API such as `.value` and `.rx`.

        Args:
            name: The attribute name to assign.
            value: The value to assign.

        Example:
            ```py
            >>> class Person:
            ...     def __init__(self, name: str):
            ...         self.name = name
            ...     def greet(self) -> str:
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
        # Internal state always belongs to the wrapper, never the wrapped value.
        if name[:1] == "_":
            super().__setattr__(name, value)
            return

        # During __init__, `_value` may not exist yet. Check it directly so we
        # do not accidentally use __getattr__ while the wrapper is only
        # partially constructed.
        try:
            object.__getattribute__(self, "_value")
        except AttributeError:
            super().__setattr__(name, value)
            return

        # Attributes defined on the wrapper itself stay on the wrapper.
        # This preserves the wrapper's API like `.value`, `.rx`, and helper
        # methods.
        if self._is_own_attr(name):
            super().__setattr__(name, value)
            return

        # For everything else, proxy the write only if the wrapped object
        # already exposes that attribute. Successful forwarded writes are
        # treated like in-place mutations, so dependents are invalidated.
        wrapped = self.value
        if hasattr(wrapped, name):
            setattr(wrapped, name, value)
            if _is_reactive_value(self):
                self._bump_version()
            self.notify()
            return

        # If the wrapped object does not own the name either, fall back to
        # normal Python assignment on the wrapper instance.
        super().__setattr__(name, value)

    def __setitem__(self, key: Any, value: Any) -> None:
        """Set an item on the underlying `self.value`.

        Note:
            It is necessary to set the item via the Signal, rather than the
            underlying `signal.value`, to properly notify downstream observers
            of changes. Reason being, mutable objects that, for example, fallback
            to id comparison for equality checks will appear as if nothing changed
            even an element of the object is changed.

        Args:
            key: The key to change.
            value: The value to set it to.

        Example:
            ```py
            >>> s = Signal([1, 2, 3])
            >>> result = computed(sum)(s)
            >>> result.value
            6
            >>> s[1] = 4
            >>> result.value
            8
        """
        if isinstance(self.value, (list, dict)):
            self.value[key] = value
            if _is_reactive_value(self):
                self._bump_version()
            self.notify()
        else:
            raise TypeError(f"'{type(self.value).__name__}' object does not support item assignment")


# Loaded after _ReactiveMixIn is defined to avoid import cycles.
from ._functions import computed, deep_unref  # noqa: E402
from ._reactive import Computed, Effect, _bump_global_version, _is_reactive_value  # noqa: E402
