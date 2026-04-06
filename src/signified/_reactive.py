"""Reactive value classes and dependency-tracking internals for :mod:`signified`."""

from __future__ import annotations

import contextvars
import math
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from enum import IntEnum
from typing import Any, Callable, Protocol, Self, TypeGuard, TypeVar, cast, overload

from ._mixin import _ReactiveMixIn
from ._scheduler import queue_batch_observer, register_task_context_default, should_batch_observers
from ._types import HasValue, ReactiveValue, _ObserverLinks
from .plugins import HOOKS_ENABLED, plugin_manager

__all__ = ["Variable", "Signal", "Computed", "Effect"]


_PLAIN_SCALAR_TYPES = {int, float, str, bool, bytes, complex, type(None)}
_GLOBAL_VERSION = 0


def _bump_global_version() -> int:
    """Advance the module-wide reactive version clock and return the new value."""
    global _GLOBAL_VERSION
    _GLOBAL_VERSION += 1
    return _GLOBAL_VERSION


def _is_reactive_value[T](value: HasValue[T]) -> TypeGuard[ReactiveValue[T]]:
    """Return whether ``value`` is a signified reactive wrapper."""
    # Note: We use a specific attribute instead of isinstance to reduce overhead.
    return getattr(type(value), "_IS_REACTIVE", False)


def _may_have_reactive_children(value: Any) -> bool:
    """Return whether `value` could contain reactive values that need subscriptions."""
    if type(value) in _PLAIN_SCALAR_TYPES:
        return False
    if _is_reactive_value(value):
        return True
    return isinstance(value, Iterable) and not isinstance(value, str)


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


class _Observer(Protocol):
    def update(self) -> None:
        pass


class Variable[T](ABC, _ReactiveMixIn[T]):
    """Abstract base class for reactive values.

    Both [Signal][signified.Signal] and [Computed][signified.Computed] extend this
    class. *You should use them directly.*

    Variable is only exposed for type hinting or subclassing purposes.
    """

    __slots__ = ["_observers", "_name", "_version", "__weakref__"]
    _IS_COMPUTED = False

    def __init__(self):
        """Initialize the variable."""
        self._observers = _ObserverLinks[_Observer]()
        self._name = ""
        self._version = 0

    @staticmethod
    def _iter_variables(item: Any) -> Generator[Variable[Any], None, None]:
        """Yield `Variable` instances found in arbitrarily nested containers."""
        if type(item) in _PLAIN_SCALAR_TYPES:
            return
        if _is_reactive_value(item):
            yield item
            return
        if isinstance(item, str):
            return
        if isinstance(item, Iterable):
            for sub_item in item:
                yield from Variable._iter_variables(sub_item)

    def subscribe(self, observer: _Observer) -> None:
        """Subscribe an observer to this variable.

        Args:
            observer: The observer to subscribe.

        Note:
            [Computed][signified.Computed] overrides this method to initialize dependency
            tracking before adding the observer, so subscribers are guaranteed
            to see all future upstream changes from the moment they subscribe.
        """
        self._observers.add(observer)

    def unsubscribe(self, observer: _Observer) -> None:
        """Unsubscribe an observer from this variable.

        Args:
            observer: The observer to unsubscribe.
        """
        self._observers.discard(observer)

    def _observe(self, items: Any) -> Self:
        """Subscribe ``self`` to all reactive values found in ``items``."""
        for item in self._iter_variables(items):
            if item is not self:
                item.subscribe(self)
        return self

    def _unobserve(self, items: Any) -> Self:
        """Unsubscribe ``self`` from all reactive values found in ``items``."""
        for item in self._iter_variables(items):
            if item is not self:
                item.unsubscribe(self)
        return self

    def notify(self) -> None:
        """Notify all observers by calling their update method."""
        if not self._observers:
            return
        if not should_batch_observers():
            self._observers.notify()
            return

        for observer in self._observers.iter_alive():
            if getattr(type(observer), "_IS_REACTIVE", False):
                observer.update()
            else:
                queue_batch_observer(observer)

    def invalidate(self) -> None:
        """Force downstream recomputation, bypassing optimization caches.

        For [Signal][signified.Signal], equivalent to `update`.
        [Computed][signified.Computed] overrides this to guarantee a full re-evaluation
        even when tracked dependency versions appear unchanged — use this
        instead of `update()` when the dependency topology may have changed.
        """
        self.update()

    def _ensure_uptodate(self) -> None:
        """Refresh this node if needed before a dependent reads its version.

        Signals are always current, so the base implementation is a no-op.
        Computed overrides this to drive lazy refresh without requiring type
        checks or exception-based attribute probing in the dependency engine.
        """
        return

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
        from ._ipython import _HAS_IPYTHON, IPythonObserver

        if not _HAS_IPYTHON:
            return

        from IPython.display import display  # pyright: ignore[reportMissingImports]

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
        if HOOKS_ENABLED:
            plugin_manager.hook.named(value=self)
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
            return self._name if self._name else f"{type(self).__name__}(id={id(self)})"
        if format_spec == "d":  # Debug
            name_part = f"name='{self._name}', " if self._name else ""
            return f"{type(self).__name__}({name_part}value={self.value!r}, id={id(self)})"
        return super().__format__(format_spec)  # Handles other format specs


_ACTIVE_COMPUTED: contextvars.ContextVar[Any | None] = contextvars.ContextVar("signified_active_computed", default=None)
"""Context-local state that tracks the Computed currently being evaluated.

Reads inside a Computed register against the active consumer in the current
context, which keeps nested evaluations isolated across asyncio tasks.

.. note:: The broader reactive graph is still optimized for single-threaded
    use. This only removes the dependency-tracking global mutable stack.
"""
register_task_context_default(_ACTIVE_COMPUTED, None)


def _track_read(variable: Variable[Any]) -> None:
    """Register `variable` as a dependency of the currently computing Computed."""
    impl = _ACTIVE_COMPUTED.get()
    if impl is None:
        # Reads outside Computed evaluation do not participate in dependency tracking.
        return
    owner = impl._owner
    if owner is variable:
        # Ignore self-reads to avoid self-dependency loops.
        return
    impl._dep_state.register_dependency(variable)


def _resolve[T](value: HasValue[T]) -> T:
    """Unwrap nested reactive containers without registering any dependencies.

    Used internally by ``.value`` property getters so that resolving a stored
    nested reactive (e.g. ``Signal(Signal(5))``) does not create a redundant
    direct subscription that bypasses the outer variable's own observe chain.
    """
    current: T | HasValue[T] = value
    if type(current) in _PLAIN_SCALAR_TYPES:
        return cast(T, current)
    while _is_reactive_value(current):
        if current._IS_COMPUTED:
            current._impl.ensure_uptodate()
        current = current._value
    return cast(T, current)


def _has_changed(previous: Any, current: Any) -> bool:
    """Best-effort change detection for assignments into reactive values.

    This function is intentionally fail-open: if comparison is ambiguous or
    raises, we treat the value as changed to avoid missing invalidations.
    """
    previous_type = type(previous)
    current_type = type(current)
    if previous_type is current_type:
        if previous_type in {int, bool, str, bytes, complex, type(None)}:
            return previous != current
        if previous_type is float:
            return not (math.isnan(previous) and math.isnan(current)) and previous != current

    # Compare callables by identity to avoid invoking custom `__eq__` logic and
    # to preserve stable references as unchanged.
    if callable(previous) or callable(current):
        return previous is not current
    # Reactive wrappers compare by identity rather than value equality.
    # Distinct wrapper objects should invalidate even if they currently resolve
    # to equal values.
    if _is_reactive_value(previous) or _is_reactive_value(current):
        return previous is not current

    # Keep NaN stable: treat NaN -> NaN as unchanged.
    if isinstance(previous, float) and isinstance(current, float) and math.isnan(previous) and math.isnan(current):
        return False

    try:
        # `==` may return non-scalar array-like values; coerce those with
        # all-elements semantics before negating.
        return not _coerce_to_bool(current == previous)
    except Exception:
        # Fail-open for exotic/buggy equality implementations.
        return True


class Signal[T](Variable[T]):
    """Mutable state.

    `Signal` stores a value and notifies observers when that value changes.
    The `value` property is read/write:

    - reading `value` returns the current plain value
    - assigning `value` updates the stored value and notifies observers if it changed


    Args:
        value: Value to wrap.

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
        self._value = value
        if _may_have_reactive_children(value):
            self._observe(value)
        if HOOKS_ENABLED:
            plugin_manager.hook.created(value=self)

    @property
    def value(self) -> T:
        """The current value.

        Getting this property returns the plain Python value, unwrapping any
        nested reactive. Setting it updates the stored value and notifies
        observers if the value changed.
        """
        if HOOKS_ENABLED:
            plugin_manager.hook.read(value=self)
        _track_read(self)
        value = self._value
        if type(value) in _PLAIN_SCALAR_TYPES:
            return cast(T, value)
        return _resolve(value)

    @value.setter
    def value(self, new_value: HasValue[T]) -> None:
        old_value = self._value
        if _has_changed(old_value, new_value):
            self._value = new_value
            self._bump_version()
            if HOOKS_ENABLED:
                plugin_manager.hook.updated(value=self)
            if _may_have_reactive_children(old_value):
                self._unobserve(old_value)
            if _may_have_reactive_children(new_value):
                self._observe(new_value)
            self.notify()

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        """Temporarily set the signal to a given value within a context.

        Restores the previous value when the context exits, even if an exception
        is raised.

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
        before = self.value
        try:
            self.value = value
            yield
        finally:
            self.value = before

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
        self._bump_version()
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


class _DependencyLink:
    """Reusable edge between a Computed consumer and one producer dependency."""

    __slots__ = ["dep", "version", "prev", "next", "active", "seen_token"]

    def __init__(self, dep: Variable[Any]) -> None:
        self.dep = dep
        self.version = -1
        self.prev: _DependencyLink | None = None
        self.next: _DependencyLink | None = None
        self.active = False
        self.seen_token = 0


class _PythonDependencyState:
    """Dependency bookkeeping with reusable producer/consumer edges."""

    __slots__ = [
        "_subscriber",
        "_head",
        "_tail",
        "_lookup",
        "_next_single",
        "_next_links",
        "_refresh_token",
        "_refresh_cursor",
        "_stable_order",
    ]

    def __init__(self, subscriber: Any) -> None:
        self._subscriber = subscriber
        self._head: _DependencyLink | None = None
        self._tail: _DependencyLink | None = None
        self._lookup: dict[Variable[Any], _DependencyLink] = {}
        self._next_single: _DependencyLink | None = None
        self._next_links: list[_DependencyLink] | None = None
        self._refresh_token = 0
        self._refresh_cursor: _DependencyLink | None = None
        self._stable_order = False

    @property
    def deps(self) -> tuple[Variable[Any], ...]:
        deps: list[Variable[Any]] = []
        current = self._head
        while current is not None:
            deps.append(current.dep)
            current = current.next
        return tuple(deps)

    def start_refresh(self) -> None:
        self._refresh_token += 1
        self._next_single = None
        self._next_links = None
        self._refresh_cursor = self._head
        self._stable_order = self._head is not None

    def register_dependency(self, dependency: Variable[Any]) -> None:
        token = self._refresh_token
        next_single = self._next_single
        next_links = self._next_links
        if next_links is None and next_single is None:
            head = self._head
            if head is not None and head.next is None and dependency is head.dep:
                link = head
            else:
                link = self._lookup.get(dependency)
                if link is None:
                    link = _DependencyLink(dependency)
                    self._lookup[dependency] = link
            if link.seen_token == token:
                return
            link.seen_token = token
            self._next_single = link
            cursor = self._refresh_cursor
            if cursor is link:
                assert cursor is not None
                self._refresh_cursor = cursor.next
            else:
                self._stable_order = False
            return

        if next_links is None:
            assert next_single is not None
            if next_single.seen_token == token and dependency is next_single.dep:
                return
            next_links = [next_single]
            self._next_links = next_links
            self._next_single = None

        link = self._lookup.get(dependency)
        if link is None:
            link = _DependencyLink(dependency)
            self._lookup[dependency] = link
        if link.seen_token == token:
            return

        link.seen_token = token
        next_links.append(link)
        cursor = self._refresh_cursor
        if cursor is link:
            assert cursor is not None
            self._refresh_cursor = cursor.next
        else:
            self._stable_order = False

    def rollback_refresh(self) -> None:
        next_single = self._next_single
        if next_single is not None and not next_single.active and self._lookup.get(next_single.dep) is next_single:
            self._lookup.pop(next_single.dep, None)
        next_links = self._next_links
        if next_links is not None:
            for link in next_links:
                if not link.active and self._lookup.get(link.dep) is link:
                    self._lookup.pop(link.dep, None)
        self._next_single = None
        self._next_links = None
        self._refresh_cursor = None
        self._stable_order = False

    def commit_refresh(self, subscriber: Any) -> None:
        del subscriber

        next_single = self._next_single
        next_links = self._next_links
        if next_links is None and next_single is not None:
            link = next_single
            if self._stable_order and self._refresh_cursor is None and self._head is link and link.next is None:
                link.version = link.dep._version
                self._next_single = None
                self._refresh_cursor = None
                self._stable_order = False
                return

            current = self._head
            while current is not None:
                next_current = current.next
                if current is not link:
                    current.dep.unsubscribe(self._subscriber)
                    current.active = False
                current.prev = None
                current.next = None
                if current is not link:
                    self._lookup.pop(current.dep, None)
                current = next_current

            if not link.active:
                link.dep.subscribe(self._subscriber)
                link.active = True
            link.version = link.dep._version
            link.prev = None
            link.next = None
            self._head = link
            self._tail = link
            self._next_single = None
            self._refresh_cursor = None
            self._stable_order = False
            return

        if next_links is None:
            current = self._head
            while current is not None:
                next_current = current.next
                current.dep.unsubscribe(self._subscriber)
                current.active = False
                current.prev = None
                current.next = None
                self._lookup.pop(current.dep, None)
                current = next_current
            self._head = None
            self._tail = None
            self._refresh_cursor = None
            self._stable_order = False
            return

        if self._stable_order and self._refresh_cursor is None:
            for link in next_links:
                link.version = link.dep._version
            self._next_single = None
            self._next_links = None
            self._refresh_cursor = None
            self._stable_order = False
            return

        current = self._head
        while current is not None:
            next_current = current.next
            if current.seen_token != self._refresh_token:
                current.dep.unsubscribe(self._subscriber)
                current.active = False
                current.prev = None
                current.next = None
                self._lookup.pop(current.dep, None)
            current = next_current

        head: _DependencyLink | None = None
        prev: _DependencyLink | None = None
        for link in next_links:
            if not link.active:
                link.dep.subscribe(self._subscriber)
                link.active = True
            link.version = link.dep._version
            link.prev = prev
            if prev is None:
                head = link
            else:
                prev.next = link
            prev = link

        if head is None:
            self._head = None
            self._tail = None
        else:
            head.prev = None
            assert prev is not None
            prev.next = None
            self._head = head
            self._tail = prev

        self._next_single = None
        self._next_links = None
        self._refresh_cursor = None
        self._stable_order = False

    def dependencies_changed(self) -> bool:
        current = self._head
        if current is None:
            return False
        if current.next is None:
            dep = current.dep
            if dep._IS_COMPUTED:
                dep._impl.ensure_uptodate()
            return current.version != dep._version
        while current is not None:
            dep = current.dep
            if dep._IS_COMPUTED:
                dep._impl.ensure_uptodate()
            if current.version != dep._version:
                return True
            current = current.next
        return False

    def clear(self) -> None:
        current = self._head
        while current is not None:
            next_current = current.next
            current.active = False
            current.prev = None
            current.next = None
            current = next_current
        self._head = None
        self._tail = None
        self._lookup.clear()
        self._next_single = None
        self._next_links = None
        self._refresh_cursor = None
        self._stable_order = False


_DependencyState = _PythonDependencyState


class _ComputedImpl:
    """Internal state and dependency tracking for :class:`Computed`."""

    __slots__ = ["_owner", "_dep_state", "_state", "_is_computing", "_global_version_seen"]

    def __init__(self, owner: "Computed[Any]") -> None:
        self._owner = owner
        self._dep_state = _DependencyState(owner)
        self._state = _State.UNINITIALIZED
        self._is_computing = False
        self._global_version_seen = -1

    @property
    def _deps(self) -> Any:
        return self._dep_state.deps

    def refresh(self) -> None:
        owner = self._owner
        if self._is_computing:
            raise RuntimeError("Cycle detected while evaluating Computed")

        forced_refresh = self._state == _State.MUST_REFRESH
        previous_value = owner._value
        had_value = self._state != _State.UNINITIALIZED

        # 1) Evaluate with dependency tracking enabled.
        self._is_computing = True
        self._dep_state.start_refresh()
        active_token = _ACTIVE_COMPUTED.set(self)
        try:
            next_value = owner._compute_fn()
        except BaseException:
            # Roll back: leave self._deps and self._state unchanged so the
            # Computed stays subscribed to its previous deps and remains stale
            # for retry on the next .value read.
            self._dep_state.rollback_refresh()
            raise
        finally:
            _ACTIVE_COMPUTED.reset(active_token)
            self._is_computing = False

        # 2) Reconcile subscriptions against the dependency set from this run.
        self._dep_state.commit_refresh(owner)

        # 3) Commit value/version if the computed result actually changed.
        self._state = _State.FRESH
        value_changed = not had_value or _has_changed(previous_value, next_value)
        if value_changed:
            owner._value = next_value
            self._global_version_seen = owner._bump_version()
            if HOOKS_ENABLED:
                plugin_manager.hook.updated(value=owner)
        elif forced_refresh:
            self._global_version_seen = owner._bump_version()
        else:
            self._global_version_seen = _GLOBAL_VERSION

    def dependencies_changed(self) -> bool:
        """Ensure stale Computed deps are current, then return True if any dep version changed."""
        return self._dep_state.dependencies_changed()

    def ensure_uptodate(self) -> None:
        # Fast path 1: already fresh.
        if self._state == _State.FRESH:
            return

        # Fast path 2: the graph has not changed since this computed last
        # became current, so a stale mark can be cleared without scanning deps.
        if self._state == _State.STALE and self._global_version_seen == _GLOBAL_VERSION:
            self._state = _State.FRESH
            return

        # Fast path 3: stale, but no dep version changed — skip recompute.
        if self._state == _State.STALE and not self.dependencies_changed():
            self._state = _State.FRESH
            self._global_version_seen = _GLOBAL_VERSION
            return

        # Slow path: recompute and reconcile dependencies.
        self.refresh()

    def invalidate(self, *, force: bool = False) -> bool:
        """Mark stale and return True when transitioning out of FRESH.

        ``force=True`` upgrades the state to ``MUST_REFRESH``, bypassing the
        dep-version check on the next read even if dep versions look unchanged.
        """
        was_fresh = self._state == _State.FRESH
        self._state = max(self._state, _State.MUST_REFRESH if force else _State.STALE)
        return was_fresh

    def clear_deps(self) -> None:
        self._dep_state.clear()


# We intentionally use a `TypeVar` here rather than PEP 695 syntax to ensure
# that Computed[T] is explicitly invariant.
#
# With inferred variance (PEP 695), internal refactors (e.g., renaming `f`
# to `_compute_fn`) can make `Computed` covariant in the type checker. That,
# in turn, causes several operator overloads on `_ReactiveMixIn` to be flagged
# as overlapping. Keeping variance explicit here avoids these subtle, brittle
# regressions.
T = TypeVar("T")


class Computed(Variable[T]):
    """Reactive value derived from a computation.

    `Computed` lazily re-runs its function and updates its value whenever a
    dependency changes. Dependencies are inferred automatically from which
    reactive values are read during evaluation.

    In most cases `Computed` instances should be created implicitly by using
    overloaded operators or the [computed][signified.computed] decorator rather
    than directly using the `Computed` class.

    Unlike [Signal][signified.Signal], `Computed.value` is read-only.

    Args:
        f: Zero-argument function used to compute the current value.

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

    __slots__ = ["_compute_fn", "_value", "_impl"]
    _IS_COMPUTED = True

    def __init__(self, f: Callable[[], T]) -> None:
        super().__init__()
        self._compute_fn = f
        self._value: T = cast(T, None)  # placeholder; always set before read via _state guard
        self._impl = _ComputedImpl(self)

        if HOOKS_ENABLED:
            plugin_manager.hook.created(value=self)

    def subscribe(self, observer: _Observer) -> None:
        """Subscribe an observer, ensuring dependency tracking is active first.

        Overrides [Variable.subscribe][signified.Variable.subscribe] to guarantee that this
        [Computed][signified.Computed] has evaluated at least once before ``observer`` is
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

    def _ensure_uptodate(self) -> None:
        self._impl.ensure_uptodate()

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
        if not self._impl.invalidate(force=True):
            return
        _bump_global_version()
        self.notify()

    @property
    def value(self) -> T:
        """Get the current value, recomputing lazily when stale."""
        if HOOKS_ENABLED:
            plugin_manager.hook.read(value=self)
        _track_read(self)
        self._impl.ensure_uptodate()
        value = self._value
        if type(value) in _PLAIN_SCALAR_TYPES:
            return value
        return _resolve(value)


class Effect:
    """Run a function (for its side effects) and re-run it whenever its reactive dependencies change.

    Any reactive value read inside `fn` — via `.value` or [unref][signified.unref] — is
    automatically tracked as a dependency. The function runs once immediately on
    construction, then again each time a dependency changes.

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

    __slots__ = ("_computed", "_disposed", "__weakref__")

    def __init__(self, fn: Callable[[], None]) -> None:
        self._computed = Computed(fn)
        self._disposed = False
        self._computed.subscribe(self)  # triggers initial evaluation

    def update(self) -> None:
        """Called by a dependency when its value changes."""
        if self._disposed:
            return
        self._computed._impl.invalidate(force=True)
        self._computed._impl.ensure_uptodate()

    def dispose(self) -> None:
        """Unsubscribe from all dependencies and stop the effect."""
        if self._disposed:
            return
        self._disposed = True
        self._computed.unsubscribe(self)
        for dep in tuple(self._computed._impl._deps):
            dep.unsubscribe(self._computed)
        self._computed._impl.clear_deps()
