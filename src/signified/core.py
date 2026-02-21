"""Core reactive programming functionality."""

from __future__ import annotations

import importlib
import importlib.util
import math
import operator
import warnings
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Concatenate, Literal, Protocol, Self, SupportsIndex, TypeGuard, Union, cast, overload

from .plugins import pm
from .types import HasValue, ReactiveValue, _OrderedWeakrefSet

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None  # User doesn't have numpy installed


__all__ = [
    "Observer",
    "ReactiveMixIn",
    "Variable",
    "Signal",
    "Computed",
    "computed",
    "unref",
    "has_value",
    "deep_unref",
    "reactive_method",
    "as_signal",
]


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


def computed[R](func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Wrap a function so calls produce a reactive ``Computed`` result.

    The returned wrapper accepts plain values, reactive values, or nested
    containers that include reactive values. On each recomputation, arguments
    are normalized with :func:`deep_unref`, so ``func`` receives plain Python
    values.

    The created :class:`Computed` tracks dependencies dynamically while the
    wrapped function runs. Any reactive value read during evaluation becomes a
    dependency for subsequent updates.

    Args:
        func: Function that computes a derived value from its inputs.

    Returns:
        A wrapper that returns a :class:`Computed` when called.

    Example:
        ```py
        >>> @computed
        ... def total(price, quantity):
        ...     return price * quantity
        >>> price = Signal(10)
        >>> quantity = Signal(2)
        >>> subtotal = total(price, quantity)
        >>> subtotal.value
        20
        >>> quantity.value = 3
        >>> subtotal.value
        30

        ```
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        def compute_func() -> R:
            resolved_args = tuple(deep_unref(arg) for arg in args)
            resolved_kwargs = {key: deep_unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func)

    return wrapper


class ReactiveMixIn[T]:
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

    def __call__[**P, R](self: "ReactiveMixIn[Callable[P, R]]", *args: P.args, **kwargs: P.kwargs) -> Computed[R]:
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

        return computed(f)(*args, **kwargs)

    @overload
    def __abs__(self: "ReactiveMixIn[complex]") -> Computed[float]: ...

    @overload
    def __abs__(self: "ReactiveMixIn[bool]") -> Computed[int]: ...

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
        return computed(abs)(self)

    def as_bool(self) -> Computed[bool]:
        """Return a reactive value for the boolean value of `self`.

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
    def __round__(self: "ReactiveMixIn[bool]") -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[bool]", ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[bool]", ndigits: int) -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[int]") -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[int]", ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[int]", ndigits: int) -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[float]") -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[float]", ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self: "ReactiveMixIn[float]", ndigits: int) -> Computed[float]: ...
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
        if ndigits is None or ndigits == 0:
            # When ndigits is None or 0, round returns an integer
            return computed(round)(self, ndigits=ndigits)
        else:
            # Otherwise, float
            return computed(round)(self, ndigits=ndigits)

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
        return computed(math.ceil)(self)

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
        return computed(math.floor)(self)

    @overload
    def __invert__(self: "ReactiveMixIn[bool]") -> Computed[int]: ...

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
        return computed(operator.inv)(self)

    @overload
    def __neg__(self: "ReactiveMixIn[bool]") -> Computed[int]: ...

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
        return computed(operator.neg)(self)

    @overload
    def __pos__(self: "ReactiveMixIn[bool]") -> Computed[int]: ...

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
        return computed(operator.pos)(self)

    @overload
    def __trunc__(self: "ReactiveMixIn[bool]") -> Computed[int]: ...

    @overload
    def __trunc__(self: "ReactiveMixIn[int]") -> Computed[int]: ...

    @overload
    def __trunc__(self: "ReactiveMixIn[float]") -> Computed[int]: ...

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
        return computed(math.trunc)(self)

    @overload
    def __add__(self: "ReactiveMixIn[float]", other: HasValue[int] | HasValue[float]) -> Computed[float]: ...

    @overload
    def __add__(self: "ReactiveMixIn[int]", other: HasValue[float]) -> Computed[float]: ...

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
        return computed(operator.add)(self, other)

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

    @overload
    def __divmod__(self: "ReactiveMixIn[int]", other: HasValue[int]) -> Computed[tuple[int, int]]: ...

    @overload
    def __divmod__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[tuple[int, int]]: ...

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
        return computed(divmod)(self, other)

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

    @overload
    def __floordiv__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return computed(operator.floordiv)(self, other)

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
        return computed(operator.lshift)(self, other)

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
        return computed(operator.matmul)(self, other)

    @overload
    def __mod__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return computed(operator.mod)(self, other)

    @overload
    def __mul__(self: "ReactiveMixIn[str]", other: HasValue[int]) -> Computed[str]: ...

    @overload
    def __mul__[V](self: "ReactiveMixIn[list[V]]", other: HasValue[int]) -> Computed[list[V]]: ...

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
        return computed(operator.mul)(self, other)

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
        return computed(operator.or_)(self, other)

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
        return computed(operator.rshift)(self, other)

    @overload
    def __pow__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return computed(operator.pow)(self, other)

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
        return computed(operator.sub)(self, other)

    @overload
    def __truediv__(self: "ReactiveMixIn[int]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __truediv__(self: "ReactiveMixIn[int]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __truediv__(self: "ReactiveMixIn[float]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __truediv__(self: "ReactiveMixIn[float]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __truediv__(
        self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int] | HasValue[float]
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
        return computed(operator.truediv)(self, other)

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
        return computed(operator.xor)(self, other)

    @overload
    def __radd__(self: "ReactiveMixIn[float]", other: HasValue[int] | HasValue[float]) -> Computed[float]: ...

    @overload
    def __radd__[R](self: "ReactiveMixIn[T]", other: HasValue[_SupportsAdd[T, R]]) -> Computed[R]: ...

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
        return computed(operator.add)(other, self)

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
        return computed(operator.and_)(other, self)

    @overload
    def __rdivmod__(self: "ReactiveMixIn[int]", other: HasValue[int]) -> Computed[tuple[int, int]]: ...

    @overload
    def __rdivmod__(self: "ReactiveMixIn[bool]", other: HasValue[int]) -> Computed[tuple[int, int]]: ...

    @overload
    def __rdivmod__(self: "ReactiveMixIn[bool]", other: HasValue[bool]) -> Computed[tuple[int, int]]: ...

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
        return computed(divmod)(other, self)

    @overload
    def __rfloordiv__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return computed(operator.floordiv)(other, self)

    @overload
    def __rmod__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return computed(operator.mod)(other, self)

    @overload
    def __rmul__(self: "ReactiveMixIn[str]", other: HasValue[int]) -> Computed[str]: ...

    @overload
    def __rmul__[V](self: "ReactiveMixIn[list[V]]", other: HasValue[int]) -> Computed[list[V]]: ...

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
        return computed(operator.mul)(other, self)

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
        return computed(operator.or_)(other, self)

    @overload
    def __rpow__(self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int]) -> Computed[int]: ...

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
        return computed(operator.pow)(other, self)

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
        return computed(operator.sub)(other, self)

    @overload
    def __rtruediv__(self: "ReactiveMixIn[int]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __rtruediv__(self: "ReactiveMixIn[int]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __rtruediv__(self: "ReactiveMixIn[float]", other: HasValue[int]) -> Computed[float]: ...

    @overload
    def __rtruediv__(self: "ReactiveMixIn[float]", other: HasValue[float]) -> Computed[float]: ...

    @overload
    def __rtruediv__(
        self: "ReactiveMixIn[bool]", other: HasValue[bool] | HasValue[int] | HasValue[float]
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
        return computed(operator.truediv)(other, self)

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
        return computed(operator.xor)(other, self)

    @overload
    def __getitem__[V](self: "ReactiveMixIn[list[V]]", key: slice) -> Computed[list[V]]: ...

    @overload
    def __getitem__[V](self: "ReactiveMixIn[tuple[V, ...]]", key: slice) -> Computed[tuple[V, ...]]: ...

    @overload
    def __getitem__(self: "ReactiveMixIn[str]", key: slice) -> Computed[str]: ...

    @overload
    def __getitem__[V](self: "ReactiveMixIn[list[V]]", key: HasValue[SupportsIndex] | HasValue[int]) -> Computed[V]: ...

    @overload
    def __getitem__[V](
        self: "ReactiveMixIn[tuple[V, ...]]", key: HasValue[SupportsIndex] | HasValue[int]
    ) -> Computed[V]: ...

    @overload
    def __getitem__(self: "ReactiveMixIn[str]", key: HasValue[SupportsIndex] | HasValue[int]) -> Computed[str]: ...

    @overload
    def __getitem__[K, V](self: "ReactiveMixIn[dict[K, V]]", key: HasValue[K]) -> Computed[V]: ...

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
        if name.startswith("_") or not hasattr(self, "_value"):
            super().__setattr__(name, value)
        elif hasattr(self.value, name):
            setattr(self.value, name, value)
            if isinstance(self, Variable):
                self._version += 1
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
            if isinstance(self, Variable):
                self._version += 1
            self.notify()
        else:
            raise TypeError(f"'{type(self.value).__name__}' object does not support item assignment")

    def where[A, B](self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]:
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


def _coerce_to_bool(value: Any) -> bool:
    """Convert a value to bool, including ambiguous array-like values.

    Some array/series-style objects raise ``ValueError`` when coerced with
    ``bool(...)``. For those, fall back to ``value.all()`` semantics so
    partial matches are treated as unequal in comparison contexts.
    """
    try:
        return bool(value)
    except ValueError:
        # Handle numpy arrays, pandas Series, and similar objects.
        return bool(value.all())


class Observer(Protocol):
    def update(self) -> None:
        pass


class Variable[T](ABC, ReactiveMixIn[T]):
    """An abstract base class for reactive values.

    A reactive value is an object that can be observed by observer for changes and
    can notify observers when its value changes. This class implements both the observer
    and observable patterns.

    This class implements both the observer and observable pattern.

    Subclasses should implement the `update` method.

    Attributes:
        _observers (list[Observer]): List of observers subscribed to this variable.
    """

    __slots__ = ["_observers", "__name", "_version", "__weakref__"]

    def __init__(self):
        """Initialize the variable."""
        self._observers = _OrderedWeakrefSet[Observer]()
        self.__name = ""
        self._version = 0

    @staticmethod
    def _iter_variables(item: Any) -> Generator[Variable[Any], None, None]:
        """Yield `Variable` instances found in arbitrarily nested containers."""
        if isinstance(item, Variable):
            yield item
            return
        if isinstance(item, str):
            return
        if isinstance(item, Iterable):
            for sub_item in item:
                yield from Variable._iter_variables(sub_item)

    def subscribe(self, observer: Observer) -> None:
        """Subscribe an observer to this variable.

        Args:
            observer: The observer to subscribe.
        """
        self._observers.add(observer)

    def unsubscribe(self, observer: Observer) -> None:
        """Unsubscribe an observer from this variable.

        Args:
            observer: The observer to unsubscribe.
        """
        self._observers.discard(observer)

    def observe(self, items: Any) -> Self:
        """Subscribe the observer (`self`) to all items that are Observable.

        This method handles arbitrarily nested iterables.

        Args:
            items: A single item, an iterable, or a nested structure of items to potentially subscribe to.

        Returns:
            self
        """

        for item in self._iter_variables(items):
            if item is not self:
                item.subscribe(self)
        return self

    def unobserve(self, items: Any) -> Self:
        """Unsubscribe the observer (`self`) from all items that are Observable.

        Args:
            items: A single item or an iterable of items to potentially unsubscribe from.

        Returns:
            self
        """

        for item in self._iter_variables(items):
            if item is not self:
                item.unsubscribe(self)
        return self

    def notify(self) -> None:
        """Notify all observers by calling their update method."""
        for observer in tuple(self._observers):
            observer.update()

    def __repr__(self) -> str:
        """Represent the object in a way that shows the inner value."""
        return f"<{self.value!r}>"

    @abstractmethod
    def update(self) -> None:
        """Update method to be overridden by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError("Update method should be overridden by subclasses")

    def _ipython_display_(self) -> None:
        from .display import _HAS_IPYTHON, IPythonObserver

        if not _HAS_IPYTHON:
            return

        try:
            display = importlib.import_module("IPython.display").display
        except ImportError:
            return

        handle = display(self.value, display_id=True)
        assert handle is not None
        IPythonObserver(self, handle)

    def add_name(self, name: str) -> Self:
        self.__name = name
        pm.hook.named(value=self)
        return self

    def __format__(self, format_spec: str) -> str:
        """Format the variable with custom display options.

        Format options:
        :n  - just the name (or type+id if unnamed)
        :d  - full debug info
        empty - just the value in brackets (default)
        """
        if not format_spec:  # Default - just show value in brackets
            return f"<{self.value}>"
        if format_spec == "n":  # Name only
            return self.__name if self.__name else f"{type(self).__name__}(id={id(self)})"
        if format_spec == "d":  # Debug
            name_part = f"name='{self.__name}', " if self.__name else ""
            return f"{type(self).__name__}({name_part}value={self.value!r}, id={id(self)})"
        return super().__format__(format_spec)  # Handles other format specs


_COMPUTE_STACK: list[Any] = []
"""Internal state that supports inferring reactive dependencies.

When a reactive value is read, we attach that read to the Computed at the
top of this stack so dependency subscriptions can be reconciled on refresh.
"""


def _track_read(variable: Variable[Any]) -> None:
    """Register `variable` as a dependency of the currently computing Computed."""
    if not _COMPUTE_STACK:
        # Reads outside Computed evaluation do not participate in dependency tracking.
        return
    owner = _COMPUTE_STACK[-1]
    if owner is variable:
        # Ignore self-reads to avoid self-dependency loops.
        return
    owner_impl = getattr(owner, "_impl", None)
    if owner_impl is not None:
        # Add this read for the current refresh run.
        owner_impl.register_dependency(variable)


def unref[T](value: HasValue[T]) -> T:
    """Resolve a value by unwrapping reactive containers until plain data remains.

    This utility repeatedly unwraps :class:`Variable` objects by following
    their internal ``_value`` references. It intentionally bypasses dependency
    tracking, which keeps this helper side-effect free inside reactive
    computations.

    Args:
        value: Plain value, reactive value, or nested reactive value.

    Returns:
        The fully unwrapped value.

    Example:
        ```py
        >>> nested = Signal(Signal(5))
        >>> unref(nested)
        5

        ```
    """
    current: Any = value
    while isinstance(current, Variable):
        if isinstance(current, Computed):
            current._impl.ensure_uptodate()
        current = current._value
    return current


def _has_changed(previous: Any, current: Any) -> bool:
    if callable(previous) or callable(current):
        return True
    if isinstance(previous, Variable) or isinstance(current, Variable):
        return previous is not current

    # Keep NaN stable: treat NaN -> NaN as unchanged.
    if isinstance(previous, float) and isinstance(current, float):
        if math.isnan(previous) and math.isnan(current):
            return False

    try:
        # `==` may return non-scalar array-like values; coerce those with
        # all-elements semantics before negating.
        return not _coerce_to_bool(current == previous)
    except Exception:
        return True


def has_value[T](obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check whether an object's resolved value is an instance of ``type_``.

    This helper is a typed guard around :func:`unref`. It is useful when code
    accepts either plain values or reactive values and needs a narrowed type
    before continuing.

    Args:
        obj: Value to inspect. May be plain or reactive.
        type_: Expected resolved value type.

    Returns:
        ``True`` if ``unref(obj)`` is an instance of ``type_``; otherwise
        ``False``.

    Example:
        ```py
        >>> candidate = Signal(42)
        >>> has_value(candidate, int)
        True
        >>> has_value(candidate, str)
        False

        ```
    """
    return isinstance(unref(obj), type_)


class Signal[T](Variable[T]):
    """Mutable source-of-truth reactive value.

    ``Signal`` stores a value and notifies subscribers when that value changes.
    It is typically used for application state that should be observed by
    derived :class:`Computed` values.

    The ``value`` property is read/write:
    - reading ``value`` returns the resolved plain value
    - assigning ``value`` updates dependencies and notifies observers when the
      value changed

    Signals can also proxy mutation operations (for example ``__setattr__`` and
    ``__setitem__``) so in-place updates on wrapped objects can still trigger
    reactivity.

    Args:
        value: Initial value to wrap. May be plain or reactive.

    Example:
        ```py
        >>> count = Signal(1)
        >>> doubled = count * 2
        >>> doubled.value
        2
        >>> count.value = 3
        >>> doubled.value
        6

        ```
    """

    __slots__ = ["_value"]

    @overload
    def __init__(self, value: ReactiveValue[T]) -> None: ...

    @overload
    def __init__(self, value: T) -> None: ...

    def __init__(self, value: HasValue[T]) -> None:
        super().__init__()
        self._value: HasValue[T] = value
        self.observe(value)
        pm.hook.created(value=self)

    @property
    def value(self) -> T:
        """Get or set the current value."""
        pm.hook.read(value=self)
        _track_read(self)
        return unref(self._value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        old_value = self._value
        if _has_changed(old_value, new_value):
            self._value = new_value
            self._version += 1
            pm.hook.updated(value=self)
            self.unobserve(old_value)
            self.observe(new_value)
            self.notify()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context."""
        before = self.value
        try:
            self.value = value
            yield
        finally:
            self.value = before

    def update(self) -> None:
        """Update the signal and notify subscribers."""
        self._version += 1
        self.notify()


class _ComputedImpl:
    """Internal state and dependency tracking for :class:`Computed`."""

    __slots__ = ["_owner", "_deps", "_next_deps", "_dirty", "_has_value", "_is_computing", "_dep_versions"]

    def __init__(self, owner: "Computed[Any]") -> None:
        self._owner = owner
        self._deps = _OrderedWeakrefSet[Variable[Any]]()
        self._next_deps: _OrderedWeakrefSet[Variable[Any]] | None = None
        self._dirty = True
        self._has_value = False
        self._is_computing = False
        self._dep_versions: dict[int, int] = {}

    def register_dependency(self, dependency: Variable[Any]) -> None:
        if self._next_deps is not None and dependency is not self._owner:
            self._next_deps.add(dependency)

    def refresh(self) -> None:
        owner = self._owner
        if self._is_computing:
            raise RuntimeError("Cycle detected while evaluating Computed")

        previous_value = owner._value
        had_value = self._has_value

        # 1) Evaluate with dependency tracking enabled.
        self._is_computing = True
        self._next_deps = _OrderedWeakrefSet[Variable[Any]]()
        _COMPUTE_STACK.append(owner)
        try:
            next_value = owner.f()
        finally:
            popped = _COMPUTE_STACK.pop()
            assert popped is owner
            next_deps = self._next_deps
            self._next_deps = None
            self._is_computing = False

        # 2) Reconcile subscriptions against the dependency set from this run.
        assert next_deps is not None
        for dep in tuple(self._deps):
            if dep not in next_deps:
                dep.unsubscribe(owner)
        for dep in tuple(next_deps):
            if dep not in self._deps:
                dep.subscribe(owner)
        self._deps = next_deps
        self._dep_versions = {id(dep): dep._version for dep in tuple(next_deps)}

        # 3) Commit value/version if the computed result actually changed.
        self._dirty = False
        self._has_value = True
        if not had_value or _has_changed(previous_value, next_value):
            owner._value = next_value
            owner._version += 1
            pm.hook.updated(value=owner)

    def dependencies_changed(self) -> bool:
        """Return True when any dependency has a newer observed version."""
        for dep in tuple(self._deps):
            if isinstance(dep, Computed):
                dep._impl.ensure_uptodate()
            if self._dep_versions.get(id(dep), -1) != dep._version:
                return True
        return False

    def ensure_uptodate(self) -> None:
        # Fast path 1: already fresh.
        if not self._dirty and self._has_value:
            return

        # Fast path 2: dirty marker is stale, but dependency versions unchanged.
        if self._has_value and not self.dependencies_changed():
            self._dirty = False
            return

        # Slow path: recompute and reconcile dependencies.
        self.refresh()

    def invalidate(self) -> bool:
        """Mark stale and return True when this call changed the marker."""
        if self._dirty:
            return False
        self._dirty = True
        return True


class Computed[T](Variable[T]):
    """Read-only reactive value derived from a computation.

    ``Computed`` tracks dependencies as it executes and lazily recalculates the
    value when it is read after dependencies change. In most usage, instances
    are created implicitly via :func:`computed`, operator overloads, or helper
    APIs such as :func:`reactive_method`.

    Unlike :class:`Signal`, ``Computed.value`` is read-only and updated by
    re-running the stored function.

    Args:
        f: Zero-argument function used to compute the current value.
        dependencies: Deprecated compatibility argument. Still accepted for
            backwards compatibility but ignored. Runtime reads determine the
            true dependency set.

    Example:
        ```py
        >>> count = Signal(2)
        >>> squared = Computed(lambda: count.value ** 2)
        >>> squared.value
        4
        >>> count.value = 5
        >>> squared.value
        25

        ```
    """

    __slots__ = ["f", "_value", "_impl"]

    def __init__(self, f: Callable[[], T], dependencies: Any = None) -> None:
        super().__init__()
        self.f = f
        self._value: Any = None
        self._impl = _ComputedImpl(self)

        if dependencies is not None:
            warnings.warn(
                "`Computed(..., dependencies=...)` is deprecated and ignored; "
                "dependencies are tracked automatically during evaluation.",
                DeprecationWarning,
                stacklevel=2,
            )

        pm.hook.created(value=self)

    def update(self) -> None:
        """Mark this computed stale and propagate invalidation."""
        if not self._impl.invalidate():
            return
        self.notify()

    @property
    def value(self) -> T:
        """Get the current value, recomputing lazily when stale."""
        pm.hook.read(value=self)
        _track_read(self)
        self._impl.ensure_uptodate()
        return unref(self._value)


# ---------------------------------------------------------------------------
# Utility functions that depend on the core types above
# ---------------------------------------------------------------------------

_SCALAR_TYPES = {int, float, str, bool, type(None)}


def deep_unref(value: Any) -> Any:
    """Recursively resolve reactive values within nested containers.

    ``deep_unref`` is the structural counterpart to :func:`unref`. It unwraps
    reactive values that appear inside supported containers while preserving the
    container type where practical.

    Supported behavior:
    - scalar primitives are returned unchanged
    - reactive values are unwrapped recursively
    - ``dict``, ``list``, and ``tuple`` contents are recursively unwrapped
    - generic iterables are reconstructed when possible; otherwise returned as-is
    - ``numpy.ndarray`` values with ``dtype=object`` are recursively unwrapped
      element-wise

    Args:
        value: Any value, possibly containing reactive values.

    Returns:
        Value with reactive nodes recursively replaced by plain values.

    Example:
        ```py
        >>> payload = {"a": Signal(1), "b": [Signal(2), 3]}
        >>> deep_unref(payload)
        {'a': 1, 'b': [2, 3]}

        ```
    """
    # Fast path for common scalar types (faster than isinstance check)
    if type(value) in _SCALAR_TYPES:
        return value

    # Base case - if it's a reactive value, resolve through `.value` so reads
    # are tracked while inside computed evaluations.
    if isinstance(value, Variable):
        return deep_unref(value.value)

    # For containers, recursively unref their elements
    if np is not None and isinstance(value, np.ndarray):
        assert np is not None
        return np.array([deep_unref(item) for item in value]).reshape(value.shape) if value.dtype == object else value
    if isinstance(value, dict):
        return {deep_unref(k): deep_unref(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(deep_unref(item) for item in value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        constructor: Any = type(value)
        try:
            return constructor(deep_unref(item) for item in value)
        except TypeError:
            return value

    return value


def reactive_method[**P, T](
    *dep_names: str,
) -> Callable[[Callable[Concatenate[Any, P], T]], Callable[Concatenate[Any, P], Computed[T]]]:
    """Deprecated helper for method-style computed values.

    This decorator now delegates to :func:`computed`. It is retained only for
    backwards compatibility and will be removed in a future release.

    Args:
        *dep_names: Deprecated compatibility argument. Ignored.

    Returns:
        A decorator that transforms an instance method into one that returns
        :class:`Computed`.
    """

    warnings.warn(
        "`reactive_method(...)` is deprecated and will be removed in a future "
        "release; use `@computed` instead. Any dependency-name arguments are "
        "ignored.",
        DeprecationWarning,
        stacklevel=2,
    )

    def decorator(func: Callable[Concatenate[Any, P], T]) -> Callable[Concatenate[Any, P], Computed[T]]:
        return cast(Callable[Concatenate[Any, P], Computed[T]], computed(func))

    return decorator


def as_signal[T](val: HasValue[T]) -> Signal[T]:
    """Normalize a value to a signal-compatible reactive object.

    If ``val`` is already reactive, it is returned unchanged to avoid wrapping
    an existing reactive node. Otherwise a new :class:`Signal` is created.

    Args:
        val: Plain value or reactive value.

    Returns:
        A reactive value suitable for APIs expecting ``Signal``-like behavior.

    Note:
        Existing reactive values are returned as-is at runtime, including
        ``Computed`` instances.

    Example:
        ```py
        >>> from signified import Signal, as_signal
        >>> as_signal(3).value
        3
        >>> s = Signal(4)
        >>> as_signal(s) is s
        True

        ```
    """
    return cast(Signal[T], val) if isinstance(val, Variable) else Signal(val)
