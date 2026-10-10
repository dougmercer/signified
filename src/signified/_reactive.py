"""Reactive value classes for :mod:`signified`.

The graph engine (dependency tracking, invalidation, refresh and effect
scheduling) lives in the Rust extension `signified._core`. The classes here
subclass its base classes together with `_ReactiveMixIn`, which provides the
operators, the attribute proxy, `.rx`, and typing.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Protocol, Self, TypeGuard, TypeVar, cast, overload

from . import _core
from ._mixin import _ReactiveMixIn
from ._types import HasValue, ReactiveValue

__all__ = ["Variable", "Signal", "Computed", "Binding", "Effect"]


@overload
def is_reactive[T](obj: HasValue[T]) -> TypeGuard[ReactiveValue[T]]: ...


@overload
def is_reactive[T, U](obj: HasValue[T] | HasValue[U]) -> TypeGuard[ReactiveValue[T] | ReactiveValue[U]]: ...


def is_reactive(obj: object) -> bool:
    """Return whether an object is a signified reactive wrapper.

    This guard narrows a plain-or-reactive [HasValue][signified.HasValue] to
    [ReactiveValue][signified.ReactiveValue] in the true branch without reading
    the wrapped value or creating a dependency.

    Args:
        obj: Value to inspect.

    Returns:
        `True` for a [Signal][signified.Signal], [Computed][signified.Computed],
        or [Binding][signified.Binding].
    """
    return getattr(type(obj), "_IS_REACTIVE", False)


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


_has_changed = _core.has_changed
"""Exact built-in scalars compare by value; other objects by identity.

Equal values retain the previous stored object. No user equality methods or
array comparisons are invoked implicitly.
"""


class _Observer(Protocol):
    def update(self) -> None:
        pass


class Variable[T](_ReactiveMixIn[T]):
    """Common base of reactive values.

    [Signal][signified.Signal], [Computed][signified.Computed], and
    [Binding][signified.Binding] extend this class. *You should use them directly.*

    Variable is only exposed for type hinting or subclassing purposes.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        _name: str

        def subscribe(self, observer: _Observer) -> None: ...
        def unsubscribe(self, observer: _Observer) -> None: ...
        def update(self) -> None: ...
        def invalidate(self) -> None: ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _reject_engine_overrides(cls)

    def __repr__(self) -> str:
        """Represent the object in a way that shows the inner value."""
        return f"<{self.value!r}>"

    def _ipython_display_(self) -> None:
        # IPython calls this hook itself, so IPython is importable whenever it runs.
        from IPython.display import display  # pyright: ignore[reportMissingImports]

        from ._ipython import IPythonObserver

        handle = display(self.value, display_id=True)
        assert handle is not None
        IPythonObserver(self, handle)

    def with_name(self, name: str) -> Self:
        """Assign a human-readable name to this reactive value.

        The name is used by plugins (e.g. for debugging or tracing) and appears
        in formatted output. It does not affect the value or reactivity.

        Args:
            name: A label for this value.

        Returns:
            `self`, to allow method chaining.
        """
        self._name = name
        hooks = _core.config.hooks
        if hooks is not None:
            hooks.named(value=self)
        return self

    def __copy__(self) -> Self:
        """Reactive values cannot be copied."""
        raise _copy_error(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Reactive values cannot be copied."""
        raise _copy_error(self)

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
            return self._name if self._name else f"{type(self).__name__}(id={id(self)})"
        if format_spec == "d":  # Debug
            name_part = f"name='{self._name}', " if self._name else ""
            return f"{type(self).__name__}({name_part}value={self.value!r}, id={id(self)})"
        return super().__format__(format_spec)  # Handles other format specs


def _copy_error(value: object) -> TypeError:
    name = type(value).__name__
    return TypeError(f"{name} objects cannot be copied; create a new {name} instead")


def _reject_engine_overrides(cls: type) -> None:
    """Fail at class creation if `cls` overrides a method the engine never calls."""
    for name in ("notify", "update"):
        if name in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} overrides {name}(), but signified never calls Python "
                f"overrides of {name}(). Use an Effect or subscribe() to react to changes."
            )


@contextmanager
def untracked() -> Generator[None, None, None]:
    """Read without subscribing the enclosing computation or effect.

    Nested computations still collect their own dependencies. Reads return
    current values and retain normal hooks and errors. Synchronous, single-
    thread use only; this context must not span await.
    """
    _core.push_untracked()
    try:
        yield
    finally:
        _core.pop_untracked()


class Signal[T](_core.Signal[T], Variable[T]):
    """Mutable state.

    `Signal` stores a value and notifies observers when that value changes.
    The `value` property is read/write:

    - reading `value` returns the exact stored value
    - assigning `value` updates the stored value and notifies observers if it changed

    Assigning any other public attribute forwards the write to the wrapped
    object; see [__setattr__][signified.Signal.__setattr__].

    Args:
        value: Value to wrap.
        equal: Optional `equal(previous, new) -> bool`. When it returns `True`,
            an assignment counts as unchanged: the previous object is kept and
            observers are not notified. See also
            [rx.with_equal][signified._mixin._ReactiveNamespace.with_equal].

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

        Attribute writes reach the wrapped object and notify observers:

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

    __slots__ = ()
    _WARN_ON_VALUE = True

    if TYPE_CHECKING:
        # Implemented by the Rust base class; declared here for type checkers
        # and the API docs.

        def __init__(self, value: T, *, equal: Callable[[T, T], bool] | None = None) -> None: ...

        @property
        def value(self) -> T:
            """The current value.

            Getting this property returns the stored Python value. Setting it
            updates the stored value and notifies observers if the value changed.
            """
            ...

        @value.setter
        def value(self, value: T) -> None: ...

        def update(self) -> None:
            """Force a notification to all observers unconditionally.

            Unlike assigning to `.value`, this does **not** check whether the stored
            value has changed. Use this when the contained object has been mutated
            in-place and change detection cannot detect the mutation (e.g. appending
            to a list stored in the signal).

            Warning:
                Every downstream [Computed][signified.Computed] that depends on this
                signal will recompute on its next `.value` read, even if the underlying
                data is unchanged. Prefer assigning to `.value` when possible.
            """
            ...

        def __setattr__(self, name: str, value: Any) -> None:
            """Forward a public attribute write to the wrapped object and notify.

            Private names and `Signal`'s own attributes (such as `value`) are
            assigned on the wrapper. Any other name must already exist on the
            wrapped object; the write is applied there and observers are notified,
            exactly like `signal[key] = value`. Unknown names raise `AttributeError`
            instead of silently creating an attribute on the wrapper.

            Only `Signal` forwards writes, because only a `Signal` owns its value.
            A [Computed][signified.Computed] holds a cache that the next refresh
            replaces, so writing through it would mutate state it does not own.

            Args:
                name: The attribute name to assign.
                value: The value to assign.

            Raises:
                AttributeError: If the wrapped object has no attribute `name`.
            """
            ...

    def __setitem__(self, key: Any, value: Any) -> None:
        """Set an item on the wrapped `list` or `dict` and notify observers.

        Assigning through the `Signal` rather than through `signal.value` is
        what notifies dependents: in-place mutation of the wrapped object is not
        observed on its own. Only `Signal` forwards item assignment, because
        only a `Signal` owns its value; a [Computed][signified.Computed] holds
        a cache that the next refresh replaces.

        Args:
            key: The key to change.
            value: The value to set it to.

        Raises:
            TypeError: If the wrapped value is not a `list` or `dict`.

        Example:
            ```py
            >>> s = Signal([1, 2, 3])
            >>> result = computed(sum)(s)
            >>> result.value
            6
            >>> s[1] = 4
            >>> result.value
            8

            ```
        """
        wrapped = self._value
        if not isinstance(wrapped, (list, dict)):
            raise TypeError(f"'{type(wrapped).__name__}' object does not support item assignment")
        wrapped[key] = value
        self.update()

    def __delitem__(self, key: Any) -> None:
        """Delete an item from the wrapped `list` or `dict` and notify observers.

        The mirror of [__setitem__][signified.Signal.__setitem__], and subject to
        the same rule: deleting through the `Signal` is what notifies dependents,
        and only a `Signal` forwards item deletion.

        Args:
            key: The key to delete.

        Raises:
            TypeError: If the wrapped value is not a `list` or `dict`.

        Example:
            ```py
            >>> s = Signal([1, 2, 3])
            >>> result = computed(sum)(s)
            >>> result.value
            6
            >>> del s[1]
            >>> result.value
            4

            ```
        """
        wrapped = self._value
        if not isinstance(wrapped, (list, dict)):
            raise TypeError(f"'{type(wrapped).__name__}' object does not support item deletion")
        del wrapped[key]
        self.update()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context.

        Restores the previous value when the context exits, even if an exception
        is raised.

        The previous version is restored along with the previous value, so a
        dependent that was not read inside the context is not left needing a
        recompute. Dependents read inside the context recompute as usual. If
        the signal is written again inside the context, exit falls back to an
        ordinary assignment.

        Args:
            value: The temporary value to set.

        Example:
            ```py
            >>> s = Signal(1)
            >>> with s.at(99):
            ...     print(s.value)
            99
            >>> s.value
            1

            ```
        """
        before = self._value
        before_version = entered_version = self._version
        try:
            self.value = value
            entered_version = self._version
            yield
        finally:
            if self._version != entered_version:
                self.value = before
            elif entered_version != before_version:
                # Versions are never reused, so `before_version` still names
                # exactly `before`. The clock still advances, so a consumer that
                # refreshed inside the context cannot take the global fast path.
                self._restore(before, before_version)


class _BindingSource[T](Signal[ReactiveValue[T]]):
    """Internal source selection; storing reactive objects here is intentional."""

    __slots__ = ()
    _WARN_ON_VALUE = False


# We intentionally use a `TypeVar` here rather than PEP 695 syntax to ensure
# that Computed[T] is explicitly invariant.
#
# With inferred variance (PEP 695), internal refactors can make `Computed`
# covariant in the type checker. That, in turn, causes several operator
# overloads on `_ReactiveMixIn` to be flagged as overlapping. Keeping variance
# explicit here avoids these subtle, brittle regressions.
T = TypeVar("T")


class Computed(_core.Computed[T], Variable[T]):
    """Reactive value derived from a computation.

    `Computed` lazily re-runs its function and updates its value whenever a
    dependency changes. Dependencies are inferred automatically from which
    reactive values are read during evaluation.

    In most cases `Computed` instances should be created implicitly by using
    overloaded operators or the [computed][signified.computed] decorator rather
    than directly using the `Computed` class.

    Unlike [Signal][signified.Signal], `Computed.value` is read-only.
    Ordinary exceptions are cached like values and re-raised on reads until a
    dependency changes or `invalidate()` forces another evaluation.

    Args:
        f: Zero-argument function used to compute the current value.
        equal: Optional `equal(previous, current) -> bool`. When it returns
            `True`, a recomputed value counts as unchanged: the previous object
            is kept and dependents are not invalidated. By default, built-in
            scalars compare by value and other objects by identity. Reads inside
            `equal` are not tracked, and an exception it raises is cached like
            an exception from `f`. See also
            [rx.with_equal][signified._mixin._ReactiveNamespace.with_equal].

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

        With `equal`, a new but equal result keeps dependents clean:

        ```py
        >>> count = Signal(2)
        >>> parity = Computed(lambda: [count.value % 2], equal=lambda a, b: a == b)
        >>> first = parity.value
        >>> count.value = 4
        >>> parity.value is first
        True

        ```
    """

    __slots__ = ()

    if TYPE_CHECKING:
        # Implemented by the Rust base class; declared here for type checkers
        # and the API docs.

        def __init__(self, f: Callable[[], T], *, equal: Callable[[T, T], bool] | None = None) -> None: ...

        @property
        def value(self) -> T:
            """Get the current value, recomputing lazily when stale."""
            ...

    def invalidate(self) -> None:
        """Force a full recomputation on the next `.value` read.

        Use this when a reactive attribute is replaced with a new object and
        the normal change-detection path may not pick up the change. Unlike a
        regular update, this always triggers re-evaluation regardless of whether
        dependencies appear unchanged.

        Warning:
            This method is fragile and should be a last resort. Incorrect use
            can cause unnecessary recomputation or missed updates. Prefer
            assigning to `.value` whenever possible, as this triggers the
            standard change-detection path.

        Example:
            ```py
            >>> external = {"value": 1}
            >>> c = Computed(lambda: external["value"])
            >>> c.value
            1
            >>> external["value"] = 99  # mutation not tracked by reactivity
            >>> c.value  # still cached
            1
            >>> c.invalidate()
            >>> c.value
            99

            ```
        """
        self._invalidate()


class Binding(Computed[T]):
    """A stable reactive handle whose current source can be replaced.

    Use a `Binding` when an object must keep the same public reactive identity
    while changing which `Signal`, `Computed`, or `Binding` supplies its value.
    Assigning a reactive object follows it, while assigning a plain value
    selects a private `Signal`.

    A `Binding` is an ordinary `Computed` over a `Signal` that holds the
    current source: it reads that signal, then reads the source's value.
    Rebinding therefore follows the normal contract. The switch invalidates
    the binding, and dependents recompute only if the resolved value changed
    under the usual equality policy.

    Args:
        source: A reactive source to follow, or an initial plain value managed
            by a private `Signal`.
    """

    __slots__ = ("_owned", "_holder")

    def __init__(self, source: T | ReactiveValue[T]) -> None:
        self._owned: Signal[T] | None
        if is_reactive(source):
            self._owned = None
        else:
            source = self._owned = Signal(cast(T, source))
        self._holder: Signal[ReactiveValue[T]] = _BindingSource(cast(ReactiveValue[T], source))
        # Reads the holder, then the source it holds, natively.
        self._init_source(self._holder)

    if TYPE_CHECKING:

        @property
        def value(self) -> T:
            """The current source's value. Assigning selects a plain value or follows a reactive source."""
            ...

        @value.setter
        def value(self, new_source: HasValue[T]) -> None: ...

    def _assign_value(self, new_source: HasValue[T]) -> None:
        """Select a plain value or follow a reactive source (`binding.value = ...`)."""
        self.set(new_source)

    @property
    def source(self) -> ReactiveValue[T]:
        """Return the exact current source without resolving it."""
        return self._holder._value

    def _select_source(self, source: ReactiveValue[T]) -> Self:
        """Follow `source`, including its future value changes."""
        if source is self:
            raise ValueError("A Binding cannot use itself as its source")
        # Sources compare by identity, so re-selecting the current source is a no-op.
        self._holder.value = source
        return self

    def set(self, source: HasValue[T]) -> Self:
        """Select a plain value or follow a reactive source."""
        if is_reactive(source):
            return self._select_source(source)

        value = cast(T, source)
        owned = self._owned
        if owned is None:
            owned = Signal(value)
            self._owned = owned
        else:
            owned.value = value

        return self._select_source(owned)

    def derive(self, build: Callable[[ReactiveValue[T]], ReactiveValue[T]]) -> Self:
        """Build and select a source from the exact pre-rebind source.

        Capturing the old source prevents the common cycle created by building
        a new computation from the `Binding` that will receive that computation.
        """
        previous = self.source
        next_source = build(previous)
        if not is_reactive(next_source):
            raise TypeError("derive() must return a Signal, Computed, or Binding")
        return self.set(next_source)

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily follow a private `Signal` holding `value`.

        The previous source is restored when the context exits, even if an
        exception is raised. Like [Signal.at][signified.Signal.at], a dependent
        that did not read the binding inside the context is not left needing a
        recompute.

        Args:
            value: The temporary plain value.
        """
        if is_reactive(value):
            raise TypeError("at() requires a plain value. Use set(source) for a reactive source.")

        restorable = self._restorable()
        before, before_version = self._value, self._version
        source = self.source
        source_version = source._version
        with self._holder.at(Signal(value)):
            try:
                yield
            finally:
                # Arm before the holder is restored, since its notification can
                # run effects that refresh this binding.
                if restorable and self._version != before_version:
                    self._arm_restore(before, before_version, self._holder, source, source_version)


class Effect(_core.Effect):
    """Run a function (for its side effects) and re-run it whenever its reactive dependencies change.

    Any reactive value read inside `fn` — via `.value` or [unref][signified.unref] — is
    automatically tracked as a dependency. The function runs once immediately on
    construction (or at batch exit), then again when dependencies change.
    Pending notifications coalesce; cascading writes may cause further runs.
    If computed dependencies refresh to unchanged outcomes, the callback is
    skipped. A new failed evaluation and recovery both count as changes.

    Warning:
        Dependencies are tracked dynamically on each run. Only values that are read on the branch executed in the last run are tracked.

        This means that if a reactive value within the function is not read, then updates to that value will not trigger the effect.

        For example: in `Effect(lambda: x.value if y.value else z.value)`, if `y.value` was truthy then only `x` and `y` will be tracked.

    The effect stays active as long as you hold a reference to this object.
    Call [Effect.dispose][signified.Effect.dispose] to stop it explicitly.

    Warning:
        The `Effect` instance **must be assigned to a variable**. If the result
        is discarded, it is immediately eligible for garbage collection and the
        effect will silently stop running:

        ```python
        Effect(lambda: print(s.value))   # GC'd immediately — never re-runs!
        e = Effect(lambda: print(s.value))  # kept alive — runs on every change
        ```

    Args:
        fn: Zero-argument callable run for its side effects.

    Example:
        ```py
        >>> seen = []
        >>> s = Signal(1)
        >>> e = Effect(lambda: seen.append(s.value))
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

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _reject_engine_overrides(cls)

    if TYPE_CHECKING:
        # Implemented by the Rust base class; declared here for type checkers
        # and the API docs.

        def __init__(self, fn: Callable[[], None]) -> None: ...

        def dispose(self) -> None:
            """Stop this effect, including any pending run. Safe to repeat."""
            ...


# Operators read instances of these classes natively; their `value` is the
# engine's own getter.
_core._register_standard_types([Signal, _BindingSource, Computed, Binding])
