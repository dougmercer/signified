"""Reactive operators and methods for reactive values."""

from __future__ import annotations

import math
import operator
from typing import TYPE_CHECKING, Any, Callable, Generic, Literal, Union, cast, overload

from .types import A, B, HasValue, R, T, Y
from .utils import computed

if TYPE_CHECKING:
    from .core import Computed


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
            return cast("Computed[int]", computed(round)(self, ndigits=ndigits))
        else:
            # Otherwise, float
            return cast("Computed[float]", computed(round)(self, ndigits=ndigits))

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
        return cast("Computed[int]", computed(math.ceil)(self))

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
        return cast("Computed[int]", computed(math.floor)(self))

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
        return cast("Computed[tuple[float, float]]", computed(divmod)(self, other))

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
            >>> from signified import Signal
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
        return cast("Computed[tuple[float, float]]", computed(divmod)(other, self))

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
