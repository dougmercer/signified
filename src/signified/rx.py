"""Internal module for rx backend system"""

from __future__ import annotations

import math
import operator
import warnings

from functools import (
    cached_property, 
    reduce,
)

from collections.abc import Generator
from typing import (
    Callable, 
    Iterable, 
    Literal, 
    Any, 
    Protocol, 
    Sequence, 
    SupportsIndex, 
    overload, 
    TYPE_CHECKING,
)

from signified import core

__all__ = ('ReactiveMixIn', )


if TYPE_CHECKING:
    from signified.types import HasValue
    from signified.core import Computed
        
    type ComputedInt = Computed[int] | Computed[bool]
    type ComputedNumeric = ComputedInt | Computed[float]

    type HasInt = HasValue[int] | HasValue[bool]
    type HasNumeric = HasInt | HasValue[float]


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


def _warn_deprecated_alias(method: str, replacement: str) -> None:
    """Warn that a legacy `ReactiveMixIn` helper method is deprecated."""
    warnings.warn(
        f"`ReactiveMixIn.{method}()` is deprecated; use `{replacement}` instead.",
        DeprecationWarning,
        stacklevel=3,
    )


class _RxOps[T]:
    """Helper methods available under ``signal.rx``."""

    __slots__ = ("_source",)

    def __init__(self, source: ReactiveMixIn[T]) -> None:
        self._source = source

    def apply[R](self, fn: Callable[[T], R]) -> Computed[R]:
        """Return a reactive value by applying ``fn`` to ``self._source``.

        Args:
            fn: Function used to transform the current source value.

        Returns:
            A reactive value for ``fn(source.value)``.

        Example:
            ```py
            >>> s = Signal(4)
            >>> doubled = s.rx.apply(lambda x: x * 2)
            >>> doubled.value
            8
            >>> s.value = 5
            >>> doubled.value
            10

            ```
        """
        return core.computed(fn)(self._source)

    def tap(self, fn: Callable[[T], Any]) -> Computed[T]:
        """Run ``fn`` for side effects and pass through the original value.

        Args:
            fn: Side-effect callback that receives the current source value.

        Returns:
            A reactive value that always equals ``source.value``.

        Example:
            ```py
            >>> seen = []
            >>> s = Signal(1)
            >>> passthrough = s.rx.tap(lambda x: seen.append(x))
            >>> passthrough.value
            1
            >>> s.value = 3
            >>> passthrough.value
            3
            >>> seen
            [1, 3]

            ```
        """

        @core.computed
        def _tap(value: T) -> T:
            fn(value)
            return value

        return _tap(self._source)

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
        return core.computed(len)(self._source)

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
        return core.computed(operator.is_)(self._source, other)

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
        return core.computed(operator.is_not)(self._source, other)

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
        return core.computed(operator.contains)(container, self._source)

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
        return core.computed(operator.contains)(self._source, other)

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
        return core.computed(operator.eq)(self._source, other)

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

        @core.computed
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
        return core.computed(bool)(self._source)

    def map[R, V](self, fn: Callable[[V], R]) -> Computed[map[R]]:
        """Return a reactive value by mapping ``fn`` to an iterable``self._source``.

        Args:
            fn: Function to be mapped to the values if the iterable source

        Returns:
            A reactive `map` object for ``map(fn, source.value)``.

        Example:
            ```py
            >>> s = Signal([2, 4, 6])
            >>> doubled = s.rx.map(lambda x: x * 2)
            >>> doubled.value  # Lazy map object
            <map object at 0x...>
            >>> list(doubled.value)
            [4, 8, 12]
            >>> s.value = [5, 10, 20]
            >>> list(doubled.value)
            [10, 20, 40]

            ```
        
        Raises:
            ValueError: If the mapped value is not iterable
        """
        if not isinstance(self._source.value, Iterable):
            raise ValueError(f'Reactive mapping requires value to be iterable')
        
        return core.computed(map)(fn, self._source)

    def filter[V](self, fn: Callable[[V], bool]) -> Computed[filter[V]]:
        """Return a reactive value with a filter applied to an iterable ``self._source``
        
        Args:
            fn: The filter function to apply to the computed ``filter`` call

        Returns:
            A reactive `filter` object for ``filter(fn, source.value)``.

        Example:
            ```py
            >>> s = Signal([1,2,3,4,5])
            >>> y = s.rx.filter(lambda i: i % 2 == 0)
            >>> y.value  # Lazy filter object
            <filter object at 0x...>
            >>> list(y.value)
            [2,4]
            >>> s.value = s.value + [6]
            >>> list(y.value)
            [2,4,6]

            ```

        Raises:
            ValueError: If the filtered value is not iterable
        """
        if not isinstance(self._source.value, Iterable):
            raise ValueError(f'Reactive filtering requires value to be iterable')

        return core.computed(filter)(fn, self._source)

    def reduce[R, V](self, fn: Callable[[V, V], R], initial: V | None = None) -> Computed[R]:
        """Return a reactive value for the reduction of an iterable ``self._source``.

        Args:
            fn: A reducer function that will be passed to the computed ``reduce`` call
            initial: Optional value or Computed value to use as the initial reducer value

        Example:
            ```py
            >>> s = Signal([1,1,1,1,1])
            >>> x = Signal(1)
            >>> y = s.rx.reduce(lambda i, j: i + j)
            >>> z = s.rx.reduce(lambda i, j: i + j, initial=x)
            >>> y.value
            5
            >>> z.value
            6
            >>> s.value = s.value + [1]
            >>> x.value = -1
            >>> y.value
            6
            >>> z.value
            6

            ```
        Raises:
            ValueError: If the filtered value is not iterable
        """
        if not isinstance(self._source.value, Iterable):
            raise ValueError(f'Reactive reducing requires value to be iterable')

        if initial is not None:
            return core.computed(reduce)(fn, self._source, initial)
        else:
            return core.computed(reduce)(fn, self._source)

# Mixin Configuration
ALLOW_DEPRECATED = True
REACTIVE_DUNDERS = frozenset({
    "__getattr__",
    "__call__",
    "__abs__",
    "__str__",
    "__round__",
    "__ceil__",
    "__floor__",
    "__invert__",
    "__neg__",
    "__pos__",
    "__trunc__",
    "__add__",
    "__divmod__",
    "__floordiv__",
    "__ge__",
    "__gt__",
    "__le__",
    "__lt__",
    "__lshift__",
    "__matmul__",
    "__mod__",
    "__mul__",
    "__ne__",
    "__or__",
    "__rshift__",
    "__pow__",
    "__sub__",
    "__truediv__",
    "__xor__",
    "__radd__",
    "__rand__",
    "__rdivmod__",
    "__rfloordiv__",
    "__rmod__",
    "__rmul__",
    "__ror__",
    "__rpow__",
    "__rsub__",
    "__rtruediv__",
    "__rxor__",
    "__iter__",
    "__next__",
    "__getitem__",
    "__setattr__",
    "__setitem__",
})

class ReactiveMixIn[T]:
    """Methods for easily creating reactive values."""
    
    @property
    def value(self) -> T:
        """The current value of the reactive object."""
        ...

    @cached_property
    def rx(self) -> _RxOps[T]:
        """Access reactive helper operations in a dedicated namespace."""
        return _RxOps(self)

    def notify(self) -> None:
        """Notify all observers by calling their ``update`` method."""
        ...

    if '__getattr__' in REACTIVE_DUNDERS:
        
        @overload
        def __getattr__(self, name: Literal["value", "_value"]) -> T: ...  # type: ignore
        @overload
        def __getattr__(self, name: str) -> Computed[Any]: ...

        def __getattr__(self, name: str) -> T | Computed[Any]:
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
            if name in {"value", "_value"}:
                return super().__getattribute__(name)

            if hasattr(self.value, name):
                return core.computed(getattr)(self, name)
            else:
                return super().__getattribute__(name)

    if '__call__' in REACTIVE_DUNDERS: 
        
        def __call__[**P, R](self: ReactiveMixIn[Callable[P, R]], *args: P.args, **kwargs: P.kwargs) -> Computed[R]:
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
                _f = getattr(self, "value")
                return _f(*args, **kwargs)

            return core.computed(f)(*args, **kwargs).observe([self, self.value])

    if '__abs__' in REACTIVE_DUNDERS: 
        
        @overload
        def __abs__(self: ReactiveMixIn[complex]) -> Computed[float]: ...
        @overload
        def __abs__(self: ReactiveMixIn[bool]) -> Computed[int]: ...
        @overload
        def __abs__(self) -> Computed[T]: ...

        def __abs__(self) -> Computed[T] | ComputedNumeric:
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
            return core.computed(abs)(self)

    if '__str__' in REACTIVE_DUNDERS:
        
        def __str__(self) -> str:
            """Return a string of the current value.

            Note:
                This is not reactive.

            Returns:
                A string representation of `self.value`.
            """
            return str(self.value)

    if '__round__' in REACTIVE_DUNDERS:
        
        @overload
        def __round__(self: ReactiveMixIn[int] | ReactiveMixIn[bool] | ReactiveMixIn[float]) -> Computed[int]: ...
        @overload
        def __round__(self: ReactiveMixIn[int] | ReactiveMixIn[bool] | ReactiveMixIn[float], ndigits: None) -> Computed[int]: ...
        @overload
        def __round__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], ndigits: HasInt) -> Computed[int]: ...
        @overload
        def __round__(self: ReactiveMixIn[float], ndigits: HasInt) -> Computed[float]: ...
        @overload
        def __round__(self, ndigits: HasInt | None = None) -> Computed[int] | Computed[float]: ...

        def __round__(self, ndigits: HasInt | None = None) -> Computed[int] | Computed[float]:
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
            if ndigits is None or ndigits == 0:
                # When ndigits is None or 0, round returns an integer
                return core.computed(round)(self, ndigits=ndigits)
            else:
                # Otherwise, float
                return core.computed(round)(self, ndigits=ndigits)

    if '__ceil__' in REACTIVE_DUNDERS:

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
            return core.computed(math.ceil)(self)

    if '__floor__' in REACTIVE_DUNDERS:
        
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
            return core.computed(math.floor)(self)

    if '__invert__' in REACTIVE_DUNDERS:
        
        @overload
        def __invert__(self: ReactiveMixIn[bool]) -> Computed[int]: ...
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
            return core.computed(operator.inv)(self)

    if '__neg__' in REACTIVE_DUNDERS:
        
        @overload
        def __neg__(self: ReactiveMixIn[bool]) -> Computed[int]: ...
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
            return core.computed(operator.neg)(self)

    if '__pos__' in REACTIVE_DUNDERS:
        
        @overload
        def __pos__(self: ReactiveMixIn[bool]) -> Computed[int]: ...
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
            return core.computed(operator.pos)(self)

    if '__trunc__' in REACTIVE_DUNDERS:
        
        @overload
        def __trunc__(self: ReactiveMixIn[int] | ReactiveMixIn[bool] | ReactiveMixIn[float]) -> Computed[int]: ...
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
            return core.computed(math.trunc)(self)

    if '__add__' in REACTIVE_DUNDERS:
        
        @overload
        def __add__(self: ReactiveMixIn[float], other: HasNumeric) -> Computed[float]: ...
        @overload
        def __add__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasValue[float]) -> Computed[float]: ...
        @overload
        def __add__[Y, R](self: _ReactiveSupportsAdd[Y, R], other: HasValue[Y]) -> Computed[R]: ...
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
            return core.computed(operator.add)(self, other)

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
            return core.computed(operator.and_)(self, other)

    if '__divmod__' in REACTIVE_DUNDERS:
        
        @overload
        def __divmod__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[tuple[int, int]]: ...
        @overload
        def __divmod__(self: ReactiveMixIn[float], other: HasNumeric) -> Computed[tuple[float, float]]: ...
        @overload
        def __divmod__(self: ReactiveMixIn[int], other: HasValue[float]) -> Computed[tuple[float, float]]: ...
        
        def __divmod__(self, other) -> Computed[tuple[int, int]] | Computed[tuple[float, float]]:
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
            return core.computed(divmod)(self, other)

    if '__floordiv__' in REACTIVE_DUNDERS:
        
        @overload
        def __floordiv__(self: ReactiveMixIn[bool], other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...
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
            return core.computed(operator.floordiv)(self, other)

    if '__ge__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.ge)(self, other)

    if '__gt__' in REACTIVE_DUNDERS:

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
            return core.computed(operator.gt)(self, other)

    if '__le__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.le)(self, other)

    if '__lt__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.lt)(self, other)

    if '__lshift__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.lshift)(self, other)

    if '__matmul__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.matmul)(self, other)

    if '__mod__' in REACTIVE_DUNDERS:
        
        @overload
        def __mod__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[int]: ...
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
            return core.computed(operator.mod)(self, other)

    if '__mul__' in REACTIVE_DUNDERS:
        
        @overload
        def __mul__(self: ReactiveMixIn[str], other: HasInt) -> Computed[str]: ...
        @overload
        def __mul__[V](self: ReactiveMixIn[list[V]], other: HasInt) -> Computed[list[V]]: ...
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
            return core.computed(operator.mul)(self, other)

    if '__ne__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.ne)(self, other)

    if '__or__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.or_)(self, other)

    if '__rshift__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.rshift)(self, other)

    if '__pow__' in REACTIVE_DUNDERS:
        
        @overload
        def __pow__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[int]: ...
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
            return core.computed(operator.pow)(self, other)

    if '__sub__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.sub)(self, other)

    if '__truediv__' in REACTIVE_DUNDERS:
        
        @overload
        def __truediv__(self: ReactiveMixIn[int] | ReactiveMixIn[bool] | ReactiveMixIn[float], other: HasNumeric) -> Computed[float]: ...
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
            return core.computed(operator.truediv)(self, other)

    if '__xor__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.xor)(self, other)

    if '__radd__' in REACTIVE_DUNDERS:

        @overload
        def __radd__(self: ReactiveMixIn[float], other: HasNumeric) -> Computed[float]: ...
        @overload
        def __radd__[R](self: ReactiveMixIn[T], other: HasValue[_SupportsAdd[T, R]]) -> Computed[R]: ...
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
            return core.computed(operator.add)(other, self)

    if '__rand__' in REACTIVE_DUNDERS:

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
            return core.computed(operator.and_)(other, self)

    if '__rdivmod__' in REACTIVE_DUNDERS:
        
        @overload
        def __rdivmod__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[tuple[int, int]]: ...
        @overload
        def __rdivmod__(self: ReactiveMixIn[float], other: HasNumeric) -> Computed[tuple[float, float]]: ...
        @overload
        def __rdivmod__(self: ReactiveMixIn[int], other: HasValue[float]) -> Computed[tuple[float, float]]: ...

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
            return core.computed(divmod)(other, self)

    if '__rfloordiv__' in REACTIVE_DUNDERS:
        
        @overload
        def __rfloordiv__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[int]: ...
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
            return core.computed(operator.floordiv)(other, self)

    if '__rmod__' in REACTIVE_DUNDERS:
        
        @overload
        def __rmod__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[int]: ...
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
            return core.computed(operator.mod)(other, self)

    if '__rmul__' in REACTIVE_DUNDERS:
        @overload
        def __rmul__(self: ReactiveMixIn[str], other: HasValue[int]) -> Computed[str]: ...
        @overload
        def __rmul__[V](self: ReactiveMixIn[list[V]], other: HasValue[int]) -> Computed[list[V]]: ...
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
            return core.computed(operator.mul)(other, self)

    if '__ror__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.or_)(other, self)

    if '__rpow__' in REACTIVE_DUNDERS:
        
        @overload
        def __rpow__(self: ReactiveMixIn[int] | ReactiveMixIn[bool], other: HasInt) -> Computed[int]: ...
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
            return core.computed(operator.pow)(other, self)

    if '__rsub__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.sub)(other, self)

    if '__rtruediv__' in REACTIVE_DUNDERS:
        
        @overload
        def __rtruediv__(self: ReactiveMixIn[int] | ReactiveMixIn[bool] | ReactiveMixIn[float], other: HasNumeric) -> Computed[float]: ...
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
            return core.computed(operator.truediv)(other, self)

    if '__rxor__' in REACTIVE_DUNDERS:
        
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
            return core.computed(operator.xor)(other, self)

    if '__iter__' in REACTIVE_DUNDERS:
    
        def __iter__[V](self: ReactiveMixIn[Iterable[V]]) -> Iterable[V]:
            return iter(self.value)

    if '__next__' in REACTIVE_DUNDERS:
        
        def __next__[V](self: ReactiveMixIn[Generator[V, Any, Any]]) -> Computed[V]:
            return core.computed(next)(self.value)

    if '__getitem__' in REACTIVE_DUNDERS:
        
        # list __getitem__
        @overload
        def __getitem__[V](self: ReactiveMixIn[list[V]], key: slice | Computed[slice]) -> Computed[list[V]]: ...
        @overload
        def __getitem__[V](self: ReactiveMixIn[tuple[V, ...]], key: slice | Computed[slice]) -> Computed[tuple[V, ...]]: ...
        @overload
        def __getitem__[V](self: ReactiveMixIn[list[V]], key: HasValue[int] | HasValue[SupportsIndex]) -> Computed[V]: ...
        @overload
        def __getitem__[V](self: ReactiveMixIn[tuple[V]], key: HasValue[int] | HasValue[SupportsIndex]) -> Computed[V]: ...
        @overload
        def __getitem__[V](self: ReactiveMixIn[str], key: HasValue[int] | HasValue[SupportsIndex]) -> Computed[str]: ...
        
        # dict __getitem__
        @overload
        def __getitem__[K, V](self: ReactiveMixIn[dict[K, V]], key: HasValue[K]) -> Computed[V]: ...
        @overload
        def __getitem__[K, V](self: _ReactiveSupportsGetItem[K, V], key: HasValue[K]) -> Computed[V]: ...
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
            return core.computed(operator.getitem)(self, key)

    if '__setattr__' in REACTIVE_DUNDERS:
        
        def __setattr__(self, name: str, value: Any) -> None:
            """Set an attribute on the underlying `self.value`.

            Note:
                It is necessary to set the attribute via the Signal, rather than the
                underlying `signal.value`, to properly notify downstream observers
                of changes. Reason being, mutable objects that, for example, fallback
                to id comparison for equality checks will appear as if nothing changed
                even if one of its attributes changed.

            Args:
                name: The name of the attribute to access.
                value: The value to set it to.

            Example:
                ```py
                    >>> class Person:
                    ...    def __init__(self, name: str):
                    ...        self.name = name
                    ...    def greet(self) -> str:
                    ...        return f"Hi, I'm {self.name}!"
                    >>> s = Signal(Person("Alice"))
                    >>> result = s.greet()
                    >>> result.value
                    "Hi, I'm Alice!"
                    >>> s.name = "Bob"  # Modify attribute on Person instance through the reactive value s
                    >>> result.value
                    "Hi, I'm Bob!"

                ```
            """
            if name == "_value" or not hasattr(self, "_value"):
                super().__setattr__(name, value)
            elif hasattr(self.value, name):
                setattr(self.value, name, value)
                self.notify()
            else:
                super().__setattr__(name, value)

    if '__setitem__' in REACTIVE_DUNDERS:
        
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
                >>> result = core.computed(sum)(s)
                >>> result.value
                6
                >>> s[1] = 4
                >>> result.value
                8
            """
            if isinstance(self.value, (list, dict)):
                self.value[key] = value
                self.notify()
            else:
                raise TypeError(f"'{type(self.value).__name__}' object does not support item assignment")

    if ALLOW_DEPRECATED:
        
        def where[A, B](self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]:
            """Return a reactive value for `a` if `self` is `True`, else `b`.

            Deprecated:
                Use ``self.rx.where(a, b)`` instead.

            Args:
                a: The value to return if `self` is `True`.
                b: The value to return if `self` is `False`.

            Returns:
                A reactive value for `a if self.value else b`.

            Example:
                ```py
                >>> condition = Signal(True)
                >>> result = condition.where("Yes", "No")
                >>> result.value
                'Yes'
                >>> condition.value = False
                >>> result.value
                'No'

                ```
            """
            _warn_deprecated_alias("where", "self.rx.where(a, b)")
            return self.rx.where(a, b)

        def is_not(self, other: Any) -> Computed[bool]:
            """Return a reactive value for whether `self` is not other.

            Deprecated:
                Use ``self.rx.is_not(other)`` instead.

            Args:
                other: The value to compare against.

            Returns:
                A reactive value for self.value is not other.

            Example:
                ```py
                >>> s = Signal(10)
                >>> other = None
                >>> result = s.is_not(other)
                >>> result.value
                True
                >>> s.value = None
                >>> result.value
                False

                ```
            """
            _warn_deprecated_alias("is_not", "self.rx.is_not(other)")
            return self.rx.is_not(other)

        def as_bool(self) -> Computed[bool]:
            """Return a reactive value for the boolean value of `self`.

            Deprecated:
                Will be removed in a future release. Use `core.computed(bool)(self)`.

            Note:
                `__bool__` cannot be implemented to return a non-`bool`, so it is provided as a method.

            Returns:
                A reactive value for `bool(self.value)`.

            Example:
                ```py
                >>> s = Signal(1)
                >>> result = s.as_bool()
                >>> result.value
                True
                >>> s.value = 0
                >>> result.value
                False

                ```
            """
            _warn_deprecated_alias("as_bool", "self.rx.as_bool()")
            return self.rx.as_bool()

        def contains(self, other: Any) -> Computed[bool]:
            """Return a reactive value for whether `other` is in `self`.

            Deprecated:
                Use ``self.rx.contains(other)`` instead.

            Args:
                other: The value to check for containment.

            Returns:
                A reactive value for `other in self.value`.

            Example:
                ```py
                >>> s = Signal([1, 2, 3, 4])
                >>> result = s.contains(3)
                >>> result.value
                True
                >>> s.value = [5, 6, 7, 8]
                >>> result.value
                False

                ```
            """
            _warn_deprecated_alias("contains", "self.rx.contains(other)")
            return self.rx.contains(other)

        def eq(self, other: Any) -> Computed[bool]:
            """Return a reactive value for whether `self` equals other.

            Deprecated:
                Use ``self.rx.eq(other)`` instead.

            Args:
                other: The value to compare against.

            Returns:
                A reactive value for self.value == other.

            Note:
                We can't overload `__eq__` because it interferes with basic Python operations.

            Example:
                ```py
                >>> s = Signal(10)
                >>> result = s.eq(10)
                >>> result.value
                True
                >>> s.value = 25
                >>> result.value
                False

                ```
            """
            _warn_deprecated_alias("eq", "self.rx.eq(other)")
            return self.rx.eq(other)
