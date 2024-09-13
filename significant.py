"""Observer pattern."""

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
    properly narrow the generic type for Signal/Computed types."""

    @property
    def value(self) -> T: ...


NestedValue = Union[T, "_HasValue[NestedValue[T]]"]
"""Insane recursive type hint to try to encode an arbitrarily nested Signal.

E.g., float | Signal[float] | Signal[Signal[float]] | Signal[Signal[Signal[float]]].
"""


class ReactiveMixIn(Generic[T]):
    """Methods for creating r"""

    @property
    def value(self) -> T: ...

    def __getattr__(self, name: str) -> Any:
        if name in {"value", "_value"}:
            return super().__getattribute__(name)

        if hasattr(self.value, name):
            return Computed(lambda: getattr(self.value, name), [self])
        else:
            return super().__getattribute__(name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if not callable(self.value):
            raise ValueError("Value is not callable.")
        return computed(self.value)(*args, **kwargs).register(self)

    def __abs__(self) -> Computed[T]:
        return computed(abs)(self)

    def bool(self) -> Computed[bool]:
        """__bool__ cannot be implemented so it is provided as a method."""
        return computed(bool)(self)

    def __str__(self) -> str:
        return str(self.value)

    @overload
    def __round__(self, ndigits: None) -> Computed[int]: ...
    @overload
    def __round__(self, ndigits: int) -> Computed[float]: ...

    def __round__(self, ndigits: int | None = None) -> Union[Computed[int], Computed[float]]:
        if ndigits is None or ndigits == 0:
            # When ndigits is None or 0, round returns an integer
            return cast(Computed[int], computed(round)(self, ndigits=ndigits))
        else:
            # Otherwise, float
            return cast(Computed[float], computed(round)(self, ndigits=ndigits))

    def __ceil__(self) -> Computed[int]:
        return cast(Computed[int], computed(math.ceil)(self))

    def __floor__(self) -> Computed[int]:
        return cast(Computed[int], computed(math.floor)(self))

    def __invert__(self) -> Computed[T]:
        return computed(operator.inv)(self)

    def __neg__(self) -> Computed[T]:
        return computed(operator.neg)(self)

    def __pos__(self) -> Computed[T]:
        return computed(operator.pos)(self)

    def __trunc__(self) -> Computed[T]:
        return computed(math.trunc)(self)

    def __add__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.add
        return computed(f)(self, other)

    def __and__(self, other: HasValue[Y]) -> Computed[bool]:
        return computed(operator.and_)(self, other)

    def __contains__(self, other: Any) -> Computed[bool]:
        return computed(operator.contains)(self, other)

    def __divmod__(self, other: Any) -> Computed[tuple[float, float]]:
        return cast(Computed[tuple[float, float]], computed(divmod)(self, other))

    def is_not(self, other: Any) -> Computed[bool]:
        return computed(operator.is_not)(self, other)

    def eq(self, other: Any) -> Computed[bool]:
        return computed(operator.eq)(self, other)

    def __floordiv__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.floordiv
        return computed(f)(self, other)

    def __ge__(self, other: Any) -> Computed[bool]:
        return computed(operator.ge)(self, other)

    def __gt__(self, other: Any) -> Computed[bool]:
        return computed(operator.gt)(self, other)

    def __le__(self, other: Any) -> Computed[bool]:
        return computed(operator.le)(self, other)

    def __lt__(self, other: Any) -> Computed[bool]:
        return computed(operator.lt)(self, other)

    def __lshift__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.lshift
        return computed(f)(self, other)

    def __matmul__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.matmul
        return computed(f)(self, other)

    def __mod__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.mod
        return computed(f)(self, other)

    def __mul__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.mul
        return computed(f)(self, other)

    def __ne__(self, other: Any) -> Computed[bool]:  # type: ignore[override]
        return computed(operator.ne)(self, other)

    def __or__(self, other: Any) -> Computed[bool]:
        return computed(operator.or_)(self, other)

    def __rshift__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.rshift
        return computed(f)(self, other)

    def __pow__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.pow
        return computed(f)(self, other)

    def __sub__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.sub
        return computed(f)(self, other)

    def __truediv__(self, other: HasValue[Y]) -> Computed[T | Y]:
        f: Callable[[T, Y], T | Y] = operator.truediv
        return computed(f)(self, other)

    def __xor__(self, other: Any) -> Computed[bool]:
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
        return computed(operator.getitem)(self, other)

    def where(self, a: HasValue[A], b: HasValue[B]) -> Computed[A | B]:

        @computed
        def ternary(a: A, b: B, self: Any) -> A | B:
            return a if self else b

        return ternary(a, b, self)


class Variable(_HasValue[Y], ReactiveMixIn[T]):  # type: ignore[misc]
    """A base class to define the behavior of a reactive variable.

    This class implements both the observer and subject pattern."""

    def __init__(self):
        self._observers: list[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def unsubscribe(self, observer: Observer) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def notify_subscribers(self) -> None:
        for subsciber in self._observers:
            subsciber.update()

    def __repr__(self) -> str:
        return f"<{self.value}>"

    def update(self) -> None:
        raise NotImplementedError("Update method should be overridden by subclasses")

    def register_one(self, item: Any) -> Self:
        """Subscribe self to item if item is a Subject and not self."""
        if isinstance(item, Variable) and item is not self:
            item.subscribe(self)
        return self

    def register(self, item: Any) -> Self:
        """Subscribe self to all items."""
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
    """A container that holds a reactive value."""

    def __init__(self, value: NestedValue[T]) -> None:
        super().__init__()
        self._value: T = cast(T, value)
        self.register(value)

    @property
    def value(self) -> T:
        return unref(self._value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        if new_value != self._value:
            self._value = cast(T, new_value)
            self.register(new_value)
            self.notify_subscribers()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        before = self.value
        try:
            before = self.value
            self.value = value
            yield
        finally:
            self.value = before

    def update(self) -> None:
        self.notify_subscribers()


class Computed(Variable[T, T]):
    """A reactive value defined by a function."""

    def __init__(self, compute_func: Callable[[], T], dependencies: Any = None) -> None:
        super().__init__()
        self._compute_func = compute_func
        if dependencies is not None:
            self.register(dependencies)
        self.update()

    def update(self) -> None:
        new_value = unref(self._compute_func())
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
        return unref(self._value)


def unref(value: HasValue[T]) -> T:
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
    return cast(Signal[T], val) if isinstance(val, Variable) else Signal(val)


ReactiveValue: TypeAlias = Computed[T] | Signal[T]
HasValue: TypeAlias = T | Computed[T] | Signal[T]


def has_value(obj: Any, type_: type[T]) -> TypeGuard[HasValue[T]]:
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
