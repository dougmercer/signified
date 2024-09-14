"""A reactive programming library for reactive values and functions.

Classes:
    Variable: Abstract base class for reactive values.
    Signal: A container for mutable reactive values.
    Computed: A container for computed reactive values (from functions).

Functions:
    unref: Dereference a potentially reactive value.
    computed: Decorator to create a Computed value from a function.
    reactive_method: Decorator to create a reactive method.
    as_signal: Convert a value to a Signal if it's not already a Variable.
    has_value: Type guard to check if an object has a value of a specific type.

Attributes:
    ReactiveValue: Union of Computed and Signal types.
    HasValue: Union of plain values, Computed, and Signal types.
    NestedValue: Recursive type for arbitrarily nested Signals.
"""

from __future__ import annotations

import math
import operator
from contextlib import contextmanager
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generator,
    Generic,
    Iterable,
    Protocol,
    Self,
    TypeAlias,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    overload,
)

import numpy as np
from IPython.display import DisplayHandle, display

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

    Using multiple inheritance along with ReactiveMixIn in Variable allows PyRight to
    properly narrow the generic type for Signal/Computed types.
    """

    @property
    def value(self) -> T: ...


NestedValue: TypeAlias = Union[T, "_HasValue[NestedValue[T]]"]
"""Insane recursive type hint to try to encode an arbitrarily nested Signals.

E.g., ``float | Signal[float] | Signal[Signal[float]] | Signal[Signal[Signal[float]]].``
"""


class ReactiveMixIn(Generic[T]):
    """Methods for easily creating reactive values."""

    @property
    def value(self) -> T:
        """The current value of the reactive object."""
        ...

    def __getattr__(self, name: str) -> Any:
        """Create a Computed for retrieving an attribute from self.value.

        Args:
            name: The name of the attribute to access.

        Returns:
            A Computed object representing the attribute access.

        Raises:
            AttributeError: If the attribute doesn't exist.
        """
        if name in {"value", "_value"}:
            return super().__getattribute__(name)

        if hasattr(self.value, name):
            return Computed(lambda: getattr(self.value, name), [self])
        else:
            return super().__getattribute__(name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Create a Computed for calling self.value(*args, **kwargs).

        Args:
            *args: Positional arguments to pass to the callable value.
            **kwargs: Keyword arguments to pass to the callable value.

        Returns:
            A Computed object representing the function call.

        Raises:
            ValueError: If the value is not callable.
        """
        if not callable(self.value):
            raise ValueError("Value is not callable.")
        return computed(self.value)(*args, **kwargs).register(self)

    def __abs__(self) -> Computed[T]:
        """Return a Computed representing the absolute value of self.

        Returns:
            A Computed object representing abs(self.value).
        """
        return computed(abs)(self)

    def bool(self) -> Computed[bool]:
        """Return a Computed representing the boolean value of self.

        Note:
            `__bool__` cannot be implemented to return a non-`bool`, so it is provided as a method.

        Returns:
            A Computed object representing bool(self.value).
        """
        return computed(bool)(self)

    def __str__(self) -> str:
        """Return a string representation of the current value.

        Note:
            This does not return a reactive value.

        Returns:
            A string representation of self.value.
        """
        return str(self.value)

    @overload
    def __round__(self, ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self, ndigits: int) -> Computed[float]: ...

    def __round__(self, ndigits: int | None = None) -> Computed[int] | Computed[float]:
        """Return a Computed representing the rounded value of self.

        Args:
            ndigits: Number of decimal places to round to.

        Returns:
            A Computed object representing round(self.value, ndigits).
        """
        if ndigits is None or ndigits == 0:
            # When ndigits is None or 0, round returns an integer
            return cast(Computed[int], computed(round)(self, ndigits=ndigits))
        else:
            # Otherwise, float
            return cast(Computed[float], computed(round)(self, ndigits=ndigits))

    def __ceil__(self) -> Computed[int]:
        """Return a Computed representing the ceiling of self.

        Returns:
            A Computed object representing math.ceil(self.value).
        """
        return cast(Computed[int], computed(math.ceil)(self))

    def __floor__(self) -> Computed[int]:
        """Return a Computed representing the floor of self.

        Returns:
            A Computed object representing math.floor(self.value).
        """
        return cast(Computed[int], computed(math.floor)(self))

    def __invert__(self) -> Computed[T]:
        """Return a Computed representing the bitwise inversion of self.

        Returns:
            A Computed object representing ~self.value.
        """
        return computed(operator.inv)(self)

    def __neg__(self) -> Computed[T]:
        """Return a Computed representing the negation of self.

        Returns:
            A Computed object representing -self.value.
        """
        return computed(operator.neg)(self)

    def __pos__(self) -> Computed[T]:
        """Return a Computed representing the positive of self.

        Returns:
            A Computed object representing +self.value.
        """
        return computed(operator.pos)(self)

    def __trunc__(self) -> Computed[T]:
        """Return a Computed representing the truncated value of self.

        Returns:
            A Computed object representing math.trunc(self.value).
        """
        return computed(math.trunc)(self)

    def __add__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing the sum of self and other.

        Args:
            other: The value to add.

        Returns:
            A Computed object representing self.value + other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.add
        return computed(f)(self, other)

    def __and__(self, other: HasValue[Y]) -> Computed[bool]:
        """Return a Computed representing the logical AND of self and other.

        Args:
            other: The value to AND with.

        Returns:
            A Computed object representing self.value and other.value.
        """
        return computed(operator.and_)(self, other)

    def __contains__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether other is in self.

        Args:
            other: The value to check for containment.

        Returns:
            A Computed object representing other in self.value.
        """
        return computed(operator.contains)(self, other)

    def __divmod__(self, other: Any) -> Computed[tuple[float, float]]:
        """Return a Computed representing the divmod of self and other.

        Args:
            other: The value to use as the divisor.

        Returns:
            A Computed object representing divmod(self.value, other).
        """
        return cast(Computed[tuple[float, float]], computed(divmod)(self, other))

    def is_not(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether self is not other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value is not other.
        """
        return computed(operator.is_not)(self, other)

    def eq(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether self equals other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value == other.
        """
        return computed(operator.eq)(self, other)

    def __floordiv__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing the floor division of self by other.

        Args:
            other: The value to use as the divisor.

        Returns:
            A Computed object representing self.value // other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.floordiv
        return computed(f)(self, other)

    def __ge__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether self is greater than or equal to other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value >= other.
        """
        return computed(operator.ge)(self, other)

    def __gt__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether self is greater than other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value > other.
        """
        return computed(operator.gt)(self, other)

    def __le__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether self is less than or equal to other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value <= other.
        """
        return computed(operator.le)(self, other)

    def __lt__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing whether self is less than other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value < other.
        """
        return computed(operator.lt)(self, other)

    def __lshift__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing self left-shifted by other.

        Args:
            other: The number of positions to shift.

        Returns:
            A Computed object representing self.value << other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.lshift
        return computed(f)(self, other)

    def __matmul__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing the matrix multiplication of self and other.

        Args:
            other: The value to multiply with.

        Returns:
            A Computed object representing self.value @ other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.matmul
        return computed(f)(self, other)

    def __mod__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing self modulo other.

        Args:
            other: The value to use as the divisor.

        Returns:
            A Computed object representing self.value % other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.mod
        return computed(f)(self, other)

    def __mul__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing the product of self and other.

        Args:
            other: The value to multiply with.

        Returns:
            A Computed object representing self.value * other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.mul
        return computed(f)(self, other)

    def __ne__(self, other: Any) -> Computed[bool]:  # type: ignore[override]
        """Return a Computed representing whether self is not equal to other.

        Args:
            other: The value to compare against.

        Returns:
            A Computed object representing self.value != other.
        """
        return computed(operator.ne)(self, other)

    def __or__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing the logical OR of self and other.

        Args:
            other: The value to OR with.

        Returns:
            A Computed object representing self.value or other.value.
        """
        return computed(operator.or_)(self, other)

    def __rshift__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing self right-shifted by other.

        Args:
            other: The number of positions to shift.

        Returns:
            A Computed object representing self.value >> other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.rshift
        return computed(f)(self, other)

    def __pow__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing self raised to the power of other.

        Args:
            other: The exponent.

        Returns:
            A Computed object representing self.value ** other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.pow
        return computed(f)(self, other)

    def __sub__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing the difference of self and other.

        Args:
            other: The value to subtract.

        Returns:
            A Computed object representing self.value - other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.sub
        return computed(f)(self, other)

    def __truediv__(self, other: HasValue[Y]) -> Computed[T | Y]:
        """Return a Computed representing self divided by other.

        Args:
            other: The value to use as the divisor.

        Returns:
            A Computed object representing self.value / other.value.
        """
        f: Callable[[T, Y], T | Y] = operator.truediv
        return computed(f)(self, other)

    def __xor__(self, other: Any) -> Computed[bool]:
        """Return a Computed representing the logical XOR of self and other.

        Args:
            other: The value to XOR with.

        Returns:
            A Computed object representing self.value ^ other.value.
        """
        return computed(operator.xor)(self, other)

    def __radd__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.add
        return computed(f)(other, self)

    def __rand__(self, other: Any) -> Computed[bool]:
        return computed(operator.and_)(other, self)

    def __rdivmod__(self, other: Any) -> Computed[tuple[float, float]]:
        return cast(Computed[tuple[float, float]], computed(divmod)(other, self))

    def __rfloordiv__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.floordiv
        return computed(f)(other, self)

    def __rmod__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.mod
        return computed(f)(other, self)

    def __rmul__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.mul
        return computed(f)(other, self)

    def __ror__(self, other: Any) -> Computed[bool]:
        return computed(operator.or_)(other, self)

    def __rpow__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.pow
        return computed(f)(other, self)

    def __rsub__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.sub
        return computed(f)(other, self)

    def __rtruediv__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[Y, T], T | Y] = operator.truediv
        return computed(f)(other, self)

    def __rxor__(self, other: Any) -> Computed[bool]:
        return computed(operator.xor)(other, self)

    def __getitem__(self, other: Any) -> Computed[Any]:
        """Return a Computed representing the item or slice of self.

        Args:
            other: The index or slice to retrieve.

        Returns:
            A Computed object representing self.value[other].
        """
        return computed(operator.getitem)(self, other)

    def where(self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]:
        """Return a Computed representing a if self is true, else b.

        Args:
            a: The value to return if self is true.
            b: The value to return if self is false.

        Returns:
            A Computed object representing a if self.value else b.
        """

        @computed
        def ternary(a: A, b: B, self: Any) -> A | B:
            return a if self else b

        return ternary(a, b, self)


class Variable(_HasValue[Y], ReactiveMixIn[T]):  # type: ignore[misc]
    """An abstract base class for reactive values.

    This class implements both the observer and observable pattern. Subclasses should
    implement the `update` method.

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

    def notify_subscribers(self) -> None:
        """Notify all subscribers by calling their update method."""
        for subsciber in self._observers:
            subsciber.update()

    def __repr__(self) -> str:
        """Represent the object in a way that shows the inner value."""
        return f"<{self.value}>"

    def update(self) -> None:
        """Update method to be overridden by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError("Update method should be overridden by subclasses")

    def register_one(self, item: Any) -> Self:
        """Subscribe self to item if item is a Subject and not self.

        Args:
            item: The item to potentially subscribe to.

        Returns:
            The instance itself.
        """
        if isinstance(item, Variable) and item is not self:
            item.subscribe(self)
        return self

    def register(self, item: Any) -> Self:
        """Subscribe self to all items.

        Args:
            item: The item or iterable of items to potentially subscribe to.

        Returns:
            The instance itself.
        """
        if not isinstance(item, Iterable) or isinstance(item, str):
            self.register_one(item)
        else:
            for item_ in item:
                self.register_one(item_)
        return self

    def _ipython_display_(self) -> None:
        handle = display(self.value, display_id=True)
        assert handle is not None
        self.subscribe(IPythonObserver(self, handle))


class Signal(Variable[NestedValue[T], T]):
    """A container that holds a reactive value.

    Args:
        value: The initial value of the signal, which can be a nested structure.

    Attributes:
        _value (NestedValue[T]): The current value of the signal.
    """

    def __init__(self, value: NestedValue[T]) -> None:
        super().__init__()
        self._value: T = cast(T, value)
        self.register(value)

    @property
    def value(self) -> T:
        """Get the current value of the signal.

        Returns:
            The current value, after resolving any nested reactive variables.
        """
        return unref(self._value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        """Set a new value for the signal, notifying subscribers if the value changes.

        Args:
            new_value: The new value, which can also be a reactive variable.
        """
        if new_value != self._value:
            self._value = cast(T, new_value)
            self.register(new_value)
            self.notify_subscribers()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context.

        Args:
            value: The temporary value to set.

        Yields:
            None
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
        self.notify_subscribers()


class Computed(Variable[T, T]):
    """A reactive value defined by a function.

    Args:
        compute_func: The function that computes the value.
        dependencies: Dependencies to register.

    Attributes:
        _f (Callable[[], T]): The function that computes the value.
        _value (T): The current computed value.
    """

    def __init__(self, compute_func: Callable[[], T], dependencies: Any = None) -> None:
        super().__init__()
        self._f = compute_func
        if dependencies is not None:
            self.register(dependencies)
        self.update()

    def update(self) -> None:
        """Update the value by evaluating the Computed's function."""
        new_value = unref(self._f())
        try:
            change = new_value != self._value
            if isinstance(change, np.ndarray):
                change = change.any()
        except AttributeError:
            change = False

        if not hasattr(self, "_value") or change:
            self._value: T = new_value
            self.notify_subscribers()

    @property
    def value(self) -> T:
        """Get the current computed value.

        Returns:
            The current computed value.
        """
        return unref(self._value)


def unref(value: HasValue[T]) -> T:
    """Dereference a value, resolving any nested reactive variables.

    Args:
        value: The value to dereference.

    Returns:
        The dereferenced value.
    """
    while isinstance(value, Variable):
        value = value._value
    return cast(T, value)


class IPythonObserver:
    def __init__(self, me: Variable[Any, Any], handle: DisplayHandle):
        self.me = me
        self.handle = handle

    def update(self) -> None:
        self.handle.update(self.me.value)


class Echo:
    def __init__(self, me: Variable[Any, Any]):
        self.me = me

    def update(self) -> None:
        print(self.me.value)


def computed(func: Callable[..., R]) -> Callable[..., Computed[R]]:
    """Decorate the function to return a Computed value.

    Args:
        func: The function to compute the value.

    Returns:
        A function that returns a Computed value.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        dependencies = [arg for arg in args if isinstance(arg, Variable)]
        dependencies.extend(value for value in kwargs.values() if isinstance(value, Variable))

        def compute_func() -> R:
            resolved_args = tuple(unref(arg) for arg in args)
            resolved_kwargs = {key: unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func, dependencies)

    return wrapper


def reactive_method(*dep_names: str) -> Callable[[Callable[..., T]], Callable[..., Computed[T]]]:
    """Decorate the method to return a Computed value.

    Args:
        *dep_names: Names of object attributes to track as dependencies.

    Returns:
        A decorator function.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., Computed[T]]:
        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Computed[T]:
            # Collect dependencies from the object
            dependencies = [getattr(self, name) for name in dep_names if hasattr(self, name)]
            dependencies.extend(arg for arg in args if isinstance(arg, Variable))
            dependencies.extend(value for value in kwargs.values() if isinstance(value, Variable))
            return Computed(lambda: func(self, *args, **kwargs), dependencies)

        return wrapper

    return decorator


def as_signal(val: HasValue[T]) -> Signal[T]:
    """Convert a value to a Signal if it's not already a Variable.

    Args:
        val: The value to convert.

    Returns:
        The value as a Signal.
    """
    return cast(Signal[T], val) if isinstance(val, Variable) else Signal(val)


ReactiveValue: TypeAlias = Computed[T] | Signal[T]
"""A reactive object that would return a value of type T when calling [`unref`][signified.unref]`(obj)`.

This type alias represents any reactive value, either a [`Computed`][signified.Computed] or
a [`Signal`][signified.Signal].

See Also:
    * [`Computed`][signified.Computed]: The class representing computed reactive values.
    * [`Signal`][signified.Signal]: The class representing mutable reactive values.
    * [`unref`][signified.unref]: Function to dereference values.
"""

HasValue: TypeAlias = T | Computed[T] | Signal[T]
"""This object would return a value of type T when calling `unref(obj)`.

This type alias represents any value that can be dereferenced, including
plain values, Computed values, and Signals.

See Also:
    * [`Computed`][signified.Computed]: The class representing computed reactive values.
    * [`Signal`][signified.Signal]: The class representing mutable reactive values.
    * [`unref`][signified.unref]: Function to dereference values.
"""


def has_value(obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
    """Check if an object has a value of a specific type.

    Args:
        obj: The object to check.
        type_: The type to check against.

    Returns:
        True if the object has a value of the specified type.
    """
    return isinstance(unref(obj), type_)


if TYPE_CHECKING:

    def blah() -> float:
        return 1.1

    def bloo() -> int:
        return 1

    a = Signal(1)
    b = Signal(a)
    c = Signal(b)
    d = Signal(Signal(Signal(Signal(Signal(1.2)))))
    e = Computed(blah)
    f = Computed(bloo)

    reveal_type(a)  # noqa
    reveal_type(b)  # noqa
    reveal_type(c)  # noqa
    reveal_type(d)  # noqa
    reveal_type(e)  # noqa

    reveal_type(a._value)  # noqa
    reveal_type(b._value)  # noqa
    reveal_type(c._value)  # noqa
    reveal_type(d._value)  # noqa
    reveal_type(e._value)  # noqa

    reveal_type(a.value)  # noqa
    reveal_type(b.value)  # noqa
    reveal_type(c.value)  # noqa
    reveal_type(d.value)  # noqa
    reveal_type(e.value)  # noqa

    # These get cluttered up with Variable[...]
    reveal_type(a + b)  # noqa
    reveal_type((a + b) + c)  # noqa

    # These are also cluttered/wrong.
    x = (a + b) + d
    reveal_type(x)  # noqa
    reveal_type(unref(x))  # noqa

    reveal_type(unref(e + 1.1))  # noqa
    reveal_type(unref(1.1 + e))  # noqa
    reveal_type(unref(b + c + 1 + f))  # noqa
    reveal_type(unref(f + b + c + 1 + f))  # noqa
    reveal_type(unref(e + e + d + 1.1))  # noqa
    reveal_type(unref(d + e + e + 1.1))  # noqa

    reveal_type(Signal(2) > 1)  # noqa
    reveal_type(Signal(2) < 1)  # noqa
    reveal_type(Signal(2) < 1)  # noqa

    a_or_b = Signal(True).where(a, b)
    reveal_type(a_or_b)  # noqa
    reveal_type(unref(a_or_b))  # noqa

    bb: Signal[int] | Computed[int] = Signal(Signal(2))
    a_or_b_sig = Signal(Signal(True)).where(e, bb)
    reveal_type(a_or_b_sig)  # noqa
    reveal_type(unref(a_or_b_sig))  # noqa

    a_or_b_mixed_signals = Signal(True).where(Signal(1.1), Signal(1))
    reveal_type(a_or_b_mixed_signals)  # noqa
    reveal_type(unref(a_or_b_mixed_signals))  # noqa

    a_or_b_mixed_computed = Signal(True).where(e, f)  # noqa
    reveal_type(a_or_b_mixed_computed)  # noqa
    reveal_type(unref(a_or_b_mixed_computed))  # noqa

    a_or_b_mixed_everything = Signal(True).where(e, Signal(1))
    reveal_type(a_or_b_mixed_signals)  # noqa
    reveal_type(unref(a_or_b_mixed_signals))  # noqa

    a_or_b_mixed_computed = Signal(True).where(e, f)
    reveal_type(a_or_b_mixed_computed)  # noqa
    reveal_type(unref(a_or_b_mixed_computed))  # noqa

    reveal_type(unref(Signal("abc")))  # noqa
    reveal_type(unref(Computed(lambda: "abc")))  # noqa

    reveal_type(unref(Signal([1, 2])))  # noqa
    reveal_type(unref(Signal((1,))))  # noqa
    reveal_type(unref(Signal(1)))  # noqa
    reveal_type(unref(Signal((1,))))  # noqa
