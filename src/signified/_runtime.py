"""Internal runtime primitives for :mod:`signified`."""

from __future__ import annotations

import importlib
import importlib.util
import math
import warnings
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from enum import IntEnum
from functools import wraps
from typing import Any, Callable, Concatenate, Protocol, Self, TypeGuard, cast, overload

from .core import ReactiveMixIn
from .plugins import pm
from .types import HasValue, ReactiveValue, _OrderedSet, _OrderedWeakrefSet

if importlib.util.find_spec("numpy") is not None:
    import numpy as np  # pyright: ignore[reportMissingImports]
else:
    np = None  # User doesn't have numpy installed


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
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Computed[R]:
        def compute_func() -> R:
            resolved_args = tuple(deep_unref(arg) for arg in args)
            resolved_kwargs = {key: deep_unref(value) for key, value in kwargs.items()}
            return func(*resolved_args, **resolved_kwargs)

        return Computed(compute_func)

    return wrapper


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

        Note:
            :class:`Computed` overrides this method to initialize dependency
            tracking before adding the observer, so subscribers are guaranteed
            to see all future upstream changes from the moment they subscribe.
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

    def invalidate(self) -> None:
        """Force downstream recomputation, bypassing optimization caches.

        For :class:`Signal`, equivalent to :meth:`update`.
        :class:`Computed` overrides this to guarantee a full re-evaluation
        even when tracked dependency versions appear unchanged — use this
        instead of ``update()`` when the dependency topology may have changed.
        """
        self.update()

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

.. note:: **Thread safety**: this is a plain module-level list and is not
    thread-safe. Concurrent reads or computations on different threads will
    corrupt dependency tracking. All reactive operations should be performed
    on a single thread.
"""


def _track_read(variable: Variable[Any]) -> None:
    """Register `variable` as a dependency of the currently computing Computed or Effect."""
    if not _COMPUTE_STACK:
        # Reads outside Computed/Effect evaluation do not participate in dependency tracking.
        return
    owner = _COMPUTE_STACK[-1]
    if owner is variable:
        # Ignore self-reads to avoid self-dependency loops.
        return
    owner_impl = getattr(owner, "_impl", None)
    if owner_impl is not None:
        # Computed: delegate to _ComputedImpl.
        owner_impl.register_dependency(variable)
    elif hasattr(owner, "register_dependency"):
        # Effect: register directly on the owner.
        owner.register_dependency(variable)


def _reconcile_deps(
    subscriber: Any, old_deps: _OrderedSet[Variable[Any]], new_deps: _OrderedSet[Variable[Any]]
) -> None:
    """Update subscriptions to reflect a change from old_deps to new_deps."""
    for dep in tuple(old_deps):
        if dep not in new_deps:
            dep.unsubscribe(subscriber)
    for dep in tuple(new_deps):
        if dep not in old_deps:
            dep.subscribe(subscriber)


def _resolve(value: Any) -> Any:
    """Unwrap nested reactive containers without registering any dependencies.

    Used internally by ``.value`` property getters so that resolving a stored
    nested reactive (e.g. ``Signal(Signal(5))``) does not create a redundant
    direct subscription that bypasses the outer variable's own observe chain.
    """
    current: Any = value
    while isinstance(current, Variable):
        if isinstance(current, Computed):
            current._impl.ensure_uptodate()
        current = current._value
    return current


def unref[T](value: HasValue[T]) -> T:
    """Resolve a value by unwrapping reactive containers until plain data remains.

    This utility repeatedly unwraps :class:`Variable` objects by following
    their ``.value`` chain. When called inside a :class:`Computed` or
    :class:`Effect` evaluation, each unwrapped reactive is registered as a
    dependency so that changes propagate correctly — the same behaviour as
    reading ``.value`` directly.

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
        _track_read(current)
        current = current._value
    return current


def _has_changed(previous: Any, current: Any) -> bool:
    """Best-effort change detection for assignments into reactive values.

    This function is intentionally fail-open: if comparison is ambiguous or
    raises, we treat the value as changed to avoid missing invalidations.
    """
    # Compare callables by identity to avoid invoking custom `__eq__` logic and
    # to preserve stable references as unchanged.
    if callable(previous) or callable(current):
        return previous is not current
    # Reactive wrappers compare by identity rather than value equality.
    # Distinct wrapper objects should invalidate even if they currently resolve
    # to equal values.
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
        # Fail-open for exotic/buggy equality implementations.
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
        return _resolve(self._value)

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
        """Force a version bump and notify all subscribers unconditionally.

        Unlike assigning to ``.value``, this method does **not** check whether
        the stored value has changed — it always increments ``_version`` and
        notifies downstream observers. Use this when the contained object has
        been mutated in-place and change detection cannot detect the mutation
        (e.g. appending to a list stored in the signal).

        .. warning::
            Because the version always advances, every downstream
            :class:`Computed` that depends on this signal will recompute on its
            next ``.value`` read, even if the underlying data is unchanged.
            Prefer assigning to ``.value`` when possible so that equality-based
            short-circuiting can prevent unnecessary recomputation.
        """
        self._version += 1
        self.notify()


class _State(IntEnum):
    """Staleness state for a :class:`Computed` value.

    Values are ordered so higher integers mean higher invalidation priority.
    ``UNINITIALIZED`` sits above ``MUST_REFRESH`` so that normal invalidation
    signals never downgrade a never-computed node to a lower-priority state.
    """

    FRESH = 0  # Value is current; no recomputation needed.
    STALE = 1  # May be out of date; dep-version check can save a recompute.
    MUST_REFRESH = 2  # Definitely out of date; recompute unconditionally on next read.
    UNINITIALIZED = 3  # Never computed; recompute on first read, but don't re-notify.


class _ComputedImpl:
    """Internal state and dependency tracking for :class:`Computed`."""

    __slots__ = ["_owner", "_deps", "_next_deps", "_state", "_is_computing", "_dep_versions"]

    def __init__(self, owner: "Computed[Any]") -> None:
        self._owner = owner
        self._deps = _OrderedSet[Variable[Any]]()
        self._next_deps: _OrderedSet[Variable[Any]] | None = None
        self._state = _State.UNINITIALIZED
        self._is_computing = False
        self._dep_versions: dict[int, int] = {}

    def register_dependency(self, dependency: Variable[Any]) -> None:
        if self._next_deps is not None and dependency is not self._owner:
            self._next_deps.add(dependency)

    def refresh(self) -> None:
        owner = self._owner
        if self._is_computing:
            raise RuntimeError("Cycle detected while evaluating Computed")

        forced_refresh = self._state == _State.MUST_REFRESH
        previous_value = owner._value
        had_value = self._state != _State.UNINITIALIZED

        # 1) Evaluate with dependency tracking enabled.
        self._is_computing = True
        self._next_deps = _OrderedSet[Variable[Any]]()
        _COMPUTE_STACK.append(owner)
        try:
            next_value = owner.f()
        except BaseException:
            # Roll back: leave self._deps and self._state unchanged so the
            # Computed stays subscribed to its previous deps and remains stale
            # for retry on the next .value read.
            popped = _COMPUTE_STACK.pop()
            assert popped is owner
            self._next_deps = None
            self._is_computing = False
            raise
        popped = _COMPUTE_STACK.pop()
        assert popped is owner
        next_deps = self._next_deps
        self._next_deps = None
        self._is_computing = False

        # 2) Reconcile subscriptions against the dependency set from this run.
        _reconcile_deps(owner, self._deps, next_deps)
        self._deps = next_deps
        self._dep_versions = {id(dep): dep._version for dep in tuple(next_deps)}

        # 3) Commit value/version if the computed result actually changed.
        self._state = _State.FRESH
        value_changed = not had_value or _has_changed(previous_value, next_value)
        if value_changed:
            owner._value = next_value
        if value_changed or forced_refresh:
            owner._version += 1
        if value_changed:
            pm.hook.updated(value=owner)

    def dependencies_changed(self) -> bool:
        """Ensure stale Computed deps are current, then return True if any dep version changed."""
        for dep in tuple(self._deps):
            if isinstance(dep, Computed):
                dep._impl.ensure_uptodate()
            if self._dep_versions.get(id(dep), -1) != dep._version:
                return True
        return False

    def ensure_uptodate(self) -> None:
        # Fast path 1: already fresh.
        if self._state == _State.FRESH:
            return

        # Fast path 2: stale, but no dep version changed — skip recompute.
        if self._state == _State.STALE and not self.dependencies_changed():
            self._state = _State.FRESH
            return

        # Slow path: recompute and reconcile dependencies.
        self.refresh()

    def invalidate(self, *, force: bool = False) -> bool:
        """Mark stale and return True when transitioning out of FRESH.

        ``force=True`` upgrades the state to ``MUST_REFRESH``, bypassing the
        dep-version check on the next read even if dep versions look unchanged.
        """
        target = _State.MUST_REFRESH if force else _State.STALE
        was_fresh = self._state == _State.FRESH
        if self._state < target:
            self._state = target
        return was_fresh


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

    def subscribe(self, observer: Observer) -> None:
        """Subscribe an observer, ensuring dependency tracking is active first.

        Overrides :meth:`Variable.subscribe` to guarantee that this
        :class:`Computed` has evaluated at least once before ``observer`` is
        added. After this call the computed is subscribed to all of its upstream
        dependencies, so any subsequent change will be forwarded to
        ``observer`` without missing any updates.
        """
        self._impl.ensure_uptodate()
        super().subscribe(observer)

    def update(self) -> None:
        """Mark this computed stale when notified by an upstream dependency."""
        if not self._impl.invalidate():
            return
        self.notify()

    def invalidate(self) -> None:
        """Force recomputation on next read, bypassing the dep-version check.

        Use this instead of ``update()`` when the dependency topology may have
        changed (for example, when a reactive attribute is replaced with a new
        object). Unlike the normal notification path, this guarantees a full
        re-evaluation and a version bump even if dep versions look unchanged.
        """
        if not self._impl.invalidate(force=True):
            return
        self.notify()

    @property
    def value(self) -> T:
        """Get the current value, recomputing lazily when stale."""
        pm.hook.read(value=self)
        _track_read(self)
        self._impl.ensure_uptodate()
        return _resolve(self._value)


class Effect:
    """Eagerly run a zero-argument callable and re-run it whenever any reactive
    value read inside it changes.

    ``Effect`` pushes itself onto the dependency-tracking stack while ``fn``
    runs, so every ``.value`` read (or :func:`unref` call) inside ``fn``
    registers as a dependency. After each run the dependency set is reconciled:
    newly-read reactives are subscribed, dropped ones are unsubscribed. This
    mirrors the dynamic dependency tracking used by :class:`Computed` but runs
    eagerly — ``fn`` fires immediately on construction and again on every
    subsequent upstream change without needing a ``.value`` read to trigger it.

    Because dependencies are inferred at runtime, conditional branches are
    handled correctly: only the signals actually read during the most recent
    run are tracked, and that set is updated automatically when the branch
    changes.

    The effect is active for as long as the caller holds a reference to this
    object. Because observers are stored as weak references, letting the
    ``Effect`` instance be garbage-collected will silently stop the effect.
    Call :meth:`dispose` to stop it explicitly before the instance is released.

    .. warning::
        The returned :class:`Effect` **must be assigned to a variable**. If the
        result is discarded the object is immediately eligible for garbage
        collection and the effect will silently stop running::

            Effect(lambda: print(s.value))  # GC'd immediately — never re-runs!
            e = Effect(lambda: print(s.value))  # kept alive — runs on every change

    Args:
        fn: Zero-argument callable run for its side effects. Every reactive
            value read via ``.value`` or :func:`unref` inside ``fn`` becomes
            a tracked dependency.

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

    __slots__ = ("_fn", "_deps", "_next_deps", "_is_running", "__weakref__")

    def __init__(self, fn: Callable[[], None]) -> None:
        self._fn = fn
        self._deps = _OrderedSet[Variable[Any]]()
        self._next_deps: _OrderedSet[Variable[Any]] | None = None
        self._is_running = False
        self._run()

    def register_dependency(self, dep: Variable[Any]) -> None:
        """Register ``dep`` as a dependency discovered during the current run."""
        if self._next_deps is not None:
            self._next_deps.add(dep)

    def _run(self) -> None:
        if self._is_running:
            raise RuntimeError("Cycle detected while evaluating Effect")
        prev_deps = self._deps
        self._next_deps = _OrderedSet[Variable[Any]]()
        self._is_running = True
        _COMPUTE_STACK.append(self)
        try:
            self._fn()
        except BaseException:
            # Roll back: leave self._deps unchanged so the Effect stays
            # subscribed to its previous deps and will retry on the next change.
            _COMPUTE_STACK.pop()
            self._next_deps = None
            self._is_running = False
            raise
        _COMPUTE_STACK.pop()
        next_deps = self._next_deps
        self._next_deps = None
        self._is_running = False
        _reconcile_deps(self, prev_deps, next_deps)
        self._deps = next_deps

    def update(self) -> None:
        """Called by a dependency when its value changes."""
        self._run()

    def dispose(self) -> None:
        """Unsubscribe from all dependencies and stop the effect."""
        for dep in self._deps:
            dep.unsubscribe(self)
        self._deps = _OrderedSet[Variable[Any]]()


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
