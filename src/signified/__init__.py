"""A reactive programming library for creating and managing reactive values and computations.

This module provides tools for building reactive systems, where changes in one value
automatically propagate to dependent values.

Classes:
    Variable: Abstract base class for reactive values.
    Signal: A container for mutable reactive values.
    Computed: A container for computed reactive values (from functions).

Functions:
    unref: Dereference a potentially reactive value.
    computed: Decorator to create a reactive value from a function.
    reactive_method: Decorator to create a reactive method.
    as_signal: Convert a value to a [`Signal`][signified.Signal] if it's not already a reactive value.
    has_value: Type guard to check if an object has a value of a specific type.

Attributes:
    ReactiveValue: Union of Computed and [`Signal`][signified.Signal] types.
    HasValue: Union of basic types and reactive types.
    NestedValue: Recursive type for arbitrarily nested reactive values.
"""

from __future__ import annotations

import math
import operator
from contextlib import contextmanager
from functools import wraps
import sys
from abc import ABC, abstractmethod
from typing import (
    Any,
    Callable,
    Generator,
    Generic,
    Iterable,
    Literal,
    Protocol,
    TypeVar,
    Union,
    cast,
    overload,
)

import numpy as np
from IPython.display import DisplayHandle, display


if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

if sys.version_info >= (3, 10):
    from typing import TypeAlias, TypeGuard

else:
    from typing_extensions import TypeAlias, TypeGuard

__all__ = [
    "Variable",
    "Signal",
    "Computed",
    "computed",
    "reactive_method",
    "unref",
    "as_signal",
    "HasValue",
    "ReactiveValue",
    "has_value",
]

T = TypeVar("T")
Y = TypeVar("Y")
R = TypeVar("R")

A = TypeVar("A")
B = TypeVar("B")


class Observer(Protocol):
    def update(self) -> None:
        pass


class _HasValue(Generic[T]):
    """Dumb thing to make pyright happy.

    Using multiple inheritance as done below somehow allows PyRight to properly
    infer T as the type returned by the ``value`` method for reactive types.
    """

    @property
    def value(self) -> T: ...


NestedValue: TypeAlias = Union[T, "_HasValue[NestedValue[T]]"]
"""Insane recursive type hint to try to encode an arbitrarily nested reactive values.

E.g., ``float | Signal[float] | Signal[Signal[float]] | Signal[Signal[Signal[float]]].``
"""


class ReactiveMixIn(Generic[T]):
    """Methods for easily creating reactive values."""

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
        if name in {"value", "_value"}:
            return super().__getattribute__(name)

        if hasattr(self.value, name):
            return computed(getattr)(self, name)
        else:
            return super().__getattribute__(name)

    @overload
    def __call__(self: "ReactiveMixIn[Callable[..., R]]", *args: Any, **kwargs: Any) -> Computed[R]: ...

    @overload
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
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

        return computed(f)(*args, **kwargs).observe([self, self.value])

    def __abs__(self) -> Computed[T]:
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
        return computed(abs)(self)

    def bool(self) -> Computed[bool]:
        """Return a reactive value for the boolean value of `self`.

        Note:
            `__bool__` cannot be implemented to return a non-`bool`, so it is provided as a method.

        Returns:
            A reactive value for `bool(self.value)`.

        Example:
            ```py
            >>> s = Signal(1)
            >>> result = s.bool()
            >>> result.value
            True
            >>> s.value = 0
            >>> result.value
            False

            ```
        """
        return computed(bool)(self)

    def __str__(self) -> str:
        """Return a string of the current value.

        Note:
            This is not reactive.

        Returns:
            A string representation of `self.value`.
        """
        return str(self.value)

    @overload
    def __round__(self) -> Computed[int]: ...
    @overload
    def __round__(self, ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self, ndigits: int) -> Computed[float]: ...

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
        if ndigits is None or ndigits == 0:
            # When ndigits is None or 0, round returns an integer
            return cast(Computed[int], computed(round)(self, ndigits=ndigits))
        else:
            # Otherwise, float
            return cast(Computed[float], computed(round)(self, ndigits=ndigits))

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
        return cast(Computed[int], computed(math.ceil)(self))

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
        return cast(Computed[int], computed(math.floor)(self))

    def __invert__(self) -> Computed[T]:
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
        return computed(operator.inv)(self)

    def __neg__(self) -> Computed[T]:
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
        return computed(operator.neg)(self)

    def __pos__(self) -> Computed[T]:
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
        return computed(operator.pos)(self)

    def __trunc__(self) -> Computed[T]:
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
        return computed(math.trunc)(self)

    def __add__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.add
        return computed(f)(self, other)

    def __and__(self, other: HasValue[Y]) -> Computed[bool]:
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
        return computed(operator.and_)(self, other)

    def contains(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `other` is in `self`.

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
        return computed(operator.contains)(self, other)

    def __divmod__(self, other: Any) -> Computed[tuple[float, float]]:
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
        return cast(Computed[tuple[float, float]], computed(divmod)(self, other))

    def is_not(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `self` is not other.

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
        return computed(operator.is_not)(self, other)

    def eq(self, other: Any) -> Computed[bool]:
        """Return a reactive value for whether `self` equals other.

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
        return computed(operator.eq)(self, other)

    def __floordiv__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.floordiv
        return computed(f)(self, other)

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
        return computed(operator.ge)(self, other)

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
        return computed(operator.gt)(self, other)

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
        return computed(operator.le)(self, other)

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
        return computed(operator.lt)(self, other)

    def __lshift__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.lshift
        return computed(f)(self, other)

    def __matmul__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.matmul
        return computed(f)(self, other)

    def __mod__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.mod
        return computed(f)(self, other)

    def __mul__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.mul
        return computed(f)(self, other)

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
        return computed(operator.ne)(self, other)

    def __or__(self, other: Any) -> Computed[bool]:
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
        return computed(operator.or_)(self, other)

    def __rshift__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.rshift
        return computed(f)(self, other)

    def __pow__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.pow
        return computed(f)(self, other)

    def __sub__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.sub
        return computed(f)(self, other)

    def __truediv__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[T, Y], T | Y] = operator.truediv
        return computed(f)(self, other)

    def __xor__(self, other: Any) -> Computed[bool]:
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
        return computed(operator.xor)(self, other)

    def __radd__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.add
        return computed(f)(other, self)

    def __rand__(self, other: Any) -> Computed[bool]:
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
        return computed(operator.and_)(other, self)

    def __rdivmod__(self, other: Any) -> Computed[tuple[float, float]]:
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
        return cast(Computed[tuple[float, float]], computed(divmod)(other, self))

    def __rfloordiv__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.floordiv
        return computed(f)(other, self)

    def __rmod__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.mod
        return computed(f)(other, self)

    def __rmul__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.mul
        return computed(f)(other, self)

    def __ror__(self, other: Any) -> Computed[bool]:
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
        return computed(operator.or_)(other, self)

    def __rpow__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.pow
        return computed(f)(other, self)

    def __rsub__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.sub
        return computed(f)(other, self)

    def __rtruediv__(self, other: HasValue[Y]) -> Computed[T | Y]:
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
        f: Callable[[Y, T], T | Y] = operator.truediv
        return computed(f)(other, self)

    def __rxor__(self, other: Any) -> Computed[bool]:
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
        return computed(operator.xor)(other, self)

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
        return computed(operator.getitem)(self, key)

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
            self.notify()
        else:
            raise TypeError(f"'{type(self.value).__name__}' object does not support item assignment")

    def where(self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]:
        """Return a reactive value for `a` if `self` is `True`, else `b`.

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

        @computed
        def ternary(a: A, b: B, self: Any) -> A | B:
            return a if self else b

        return ternary(a, b, self)


class Variable(ABC, _HasValue[Y], ReactiveMixIn[T]):  # type: ignore[misc]
    """An abstract base class for reactive values.

    A reactive value is an object that can be observed by observer for changes and
    can notify observers when its value changes. This class implements both the observer
    and observable patterns.

    This class implements both the observer and observable pattern.

    Subclasses should implement the `update` method.

    Attributes:
        _observers (list[Observer]): List of observers subscribed to this variable.
    """

    def __init__(self):
        """Initialize the variable."""
        self._observers: list[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        """Subscribe an observer to this variable.

        Args:
            observer: The observer to subscribe.
        """
        if observer not in self._observers:
            self._observers.append(observer)

    def unsubscribe(self, observer: Observer) -> None:
        """Unsubscribe an observer from this variable.

        Args:
            observer: The observer to unsubscribe.
        """
        if observer in self._observers:
            self._observers.remove(observer)

    def observe(self, items: Any) -> Self:
        """Subscribe the observer (`self`) to all items that are Observable.

        This method handles arbitrarily nested iterables.

        Args:
            items: A single item, an iterable, or a nested structure of items to potentially subscribe to.

        Returns:
            self
        """

        def _observe(item: Any) -> None:
            if isinstance(item, Variable) and item is not self:
                item.subscribe(self)
            elif isinstance(item, Iterable) and not isinstance(item, str):
                for sub_item in item:
                    _observe(sub_item)

        _observe(items)
        return self

    def unobserve(self, items: Any) -> Self:
        """Unsubscribe the observer (`self`) from all items that are Observable.

        Args:
            items: A single item or an iterable of items to potentially unsubscribe from.

        Returns:
            self
        """

        def _unobserve(item: Any) -> None:
            if isinstance(item, Variable) and item is not self:
                item.subscribe(self)
            elif isinstance(item, Iterable) and not isinstance(item, str):
                for sub_item in item:
                    _unobserve(sub_item)

        _unobserve(items)
        return self

    def notify(self) -> None:
        """Notify all observers by calling their update method."""
        for observer in self._observers:
            observer.update()

    def __repr__(self) -> str:
        """Represent the object in a way that shows the inner value."""
        return f"<{self.value}>"

    @abstractmethod
    def update(self) -> None:
        """Update method to be overridden by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError("Update method should be overridden by subclasses")

    def _ipython_display_(self) -> None:
        handle = display(self.value, display_id=True)
        assert handle is not None
        IPythonObserver(self, handle)


class Signal(Variable[NestedValue[T], T]):
    """A container that holds a reactive value.

    Note:
        A Signal is a Generic container with type ``T``. ``T`` is defined as the type
        that would be returned by ``signal.value`` which automatically handles
        unnesting reactive values. For example the below expression would be
        inferred by ``pyright`` to be of type ``Signal[str]``.
        ```py
        Signal(Signal(Signal("abc")))  # Signal[str]
        ```

    Args:
        value: The initial value of the signal, which can be a nested structure.

    Attributes:
        _value (NestedValue[T]): The current value of the signal.
    """

    def __init__(self, value: NestedValue[T]) -> None:
        super().__init__()
        self._value: T = cast(T, value)
        self.observe(value)

    @property
    def value(self) -> T:
        """Get or set the current value.

        When setting a value, observers will be notified if the value has changed.

        Returns:
            The current value (when getting).
        """
        return unref(self._value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        old_value = self._value
        change = new_value != old_value
        if isinstance(change, np.ndarray):
            change = change.any()
        elif callable(old_value):
            change = True
        if change:
            self._value = cast(T, new_value)
            self.unobserve(old_value)
            self.observe(new_value)
            self.notify()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context.

        Args:
            value: The temporary value to set.

        Yields:
            None

        Example:
            ```py
            >>> x = Signal(2)
            >>> x_plus_2 = x + 2
            >>> x_plus_2.value
            4
            >>> with x.at(8):
            ...     x_plus_2.value
            10

            ```
        """
        before = self.value
        try:
            before = self.value
            self.value = value
            yield
        finally:
            self.value = before

    def update(self) -> None:
        """Update the signal and notify subscribers."""
        self.notify()


class Computed(Variable[T, T]):
    """A reactive value defined by a function.

    Args:
        f: The function that computes the value.
        dependencies: Dependencies to observe.

    Attributes:
        f (Callable[[], T]): The function that computes the value.
        _value (T): The current computed value.
    """

    def __init__(self, f: Callable[[], T], dependencies: Any = None) -> None:
        super().__init__()
        self.f = f
        self.observe(dependencies)
        self._value = unref(self.f())
        self.notify()

    def update(self) -> None:
        """Update the value by re-evaluating the function."""
        new_value = self.f()
        change = new_value != self._value
        if isinstance(change, np.ndarray):
            change = change.any()
        elif callable(self._value):
            change = True

        if change:
            self._value: T = new_value
            self.notify()

    @property
    def value(self) -> T:
        """Get the current value.

        Returns:
            The current value.
        """
        return unref(self._value)


def unref(value: HasValue[T]) -> T:
    """Dereference a value, resolving any nested reactive variables.

    Args:
        value: The value to dereference.

    Returns:
        The dereferenced value.

    Example:
        ```py
        >>> x = Signal(Signal(Signal(2)))
        >>> unref(x)
        2
    """
    while isinstance(value, Variable):
        value = value._value
    return cast(T, value)


class IPythonObserver:
    def __init__(self, me: Variable[Any, Any], handle: DisplayHandle):
        self.me = me
        self.handle = handle
        me.subscribe(self)

    def update(self) -> None:
        self.handle.update(self.me.value)


class Echo:
    def __init__(self, me: Variable[Any, Any]):
        self.me = me
        me.subscribe(self)

    def update(self) -> None:
        print(self.me.value)


def computed(func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Decorate the function to return a reactive value.

    Args:
        func: The function to compute the value.

    Returns:
        A function that returns a reactive value.

    Examples:
        ```py
        >>> x = Signal([1,2,3])
        >>> sum_x = computed(sum)(x)
        >>> sum_x
        <6>
        >>> x.value = range(10)
        >>> sum_x
        <45>

        ```

        ```py
        >>> @computed
        ... def my_add(x, y):
        ...     return x + y
        >>> x = Signal(2)
        >>> my_add(x, 10)
        <12>

        ```
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        def compute_func() -> R:
            resolved_args = tuple(unref(arg) for arg in args)
            resolved_kwargs = {key: unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func, (*args, *kwargs.values()))

    return wrapper


def reactive_method(*dep_names: str) -> Callable[[Callable[..., T]], Callable[..., Computed[T]]]:
    """Decorate the method to return a reactive value.

    Args:
        *dep_names: Names of object attributes to track as dependencies.

    Returns:
        A decorator function.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., Computed[T]]:
        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Computed[T]:
            object_deps = [getattr(self, name) for name in dep_names if hasattr(self, name)]
            all_deps = (*object_deps, *args, *kwargs.values())
            return Computed(lambda: func(self, *args, **kwargs), all_deps)

        return wrapper

    return decorator


def as_signal(val: HasValue[T]) -> Signal[T]:
    """Convert a value to a [`Signal`][signified.Signal] if it's not already a reactive value.

    Args:
        val: The value to convert.

    Returns:
        The value as a [`Signal`][signified.Signal] or the original reactive value.

    Example:
        ```py
        >>> as_signal(2)
        <2>
        >>> as_signal(Signal(2))
        <2>
    """
    return cast(Signal[T], val) if isinstance(val, Variable) else Signal(val)


ReactiveValue: TypeAlias = Union[Computed[T], Signal[T]]
"""A reactive object that would return a value of type T when calling [`unref`][signified.unref]`(obj)`.

This type alias represents any reactive value, either a [`Computed`][signified.Computed] or
a [`Signal`][signified.Signal].

See Also:
    * [`Computed`][signified.Computed]: The class for computed reactive values.
    * [`Signal`][signified.Signal]: The class for mutable reactive values.
    * [`unref`][signified.unref]: Function to dereference values.
"""

HasValue: TypeAlias = Union[T, Computed[T], Signal[T]]
"""This object would return a value of type T when calling `unref(obj)`.

This type alias represents any value that can be dereferenced, including
plain values and reactive values.

See Also:
    * [`Computed`][signified.Computed]: The class for computed reactive values.
    * [`Signal`][signified.Signal]: The class for mutable reactive values.
    * [`unref`][signified.unref]: Function to dereference values.
"""


def has_value(obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check if an object has a value of a specific type.

    Note:
        This serves as a TypeGuard to help support type narrowing.

    Args:
        obj: The object to check.
        type_: The type to check against.

    Returns:
        True if the object has a value of the specified type.

    Example:
        ```py
        >>> has_value(Signal("abc"), str)
        True

        ```
    """
    return isinstance(unref(obj), type_)
