"""Reactive value classes and dependency-tracking internals for :mod:`signified`."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from enum import IntEnum
from typing import Any, Callable, Protocol, Self, TypeGuard, TypeVar, cast

from ._mixin import _ReactiveMixIn
from ._types import HasValue, ReactiveValue, _ObserverLinks
from .plugins import HOOKS_ENABLED, plugin_manager

__all__ = ["Variable", "Signal", "Computed", "Binding", "Effect"]


_GLOBAL_VERSION = 0

# `_ReactiveMixIn.__setattr__` forwards unknown names to the wrapped value, so
# it costs a Python-level call on every assignment. Internal writes on the hot
# path bypass it; `_ReactiveMixIn._bump_version` does the same.
_setattr = object.__setattr__
_BINDING_UNSET = object()


def _bump_global_version() -> int:
    """Advance the module-wide reactive version clock and return the new value."""
    global _GLOBAL_VERSION
    _GLOBAL_VERSION += 1
    return _GLOBAL_VERSION


def _is_reactive_value[T](value: HasValue[T]) -> TypeGuard[ReactiveValue[T]]:
    """Return whether ``value`` is a signified reactive wrapper."""
    # Note: We use a specific attribute instead of isinstance to reduce overhead.
    return getattr(type(value), "_IS_REACTIVE", False)


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

    [Signal][signified.Signal], [Computed][signified.Computed], and
    [Binding][signified.Binding] extend this class. *You should use them directly.*

    Variable is only exposed for type hinting or subclassing purposes.
    """

    __slots__ = ["_observers", "_name", "_version", "__weakref__"]
    _IS_COMPUTED = False

    def __init__(self):
        """Initialize the variable."""
        _setattr(self, "_observers", _ObserverLinks[_Observer]())
        _setattr(self, "_name", "")
        _setattr(self, "_version", 0)

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

    def notify(self) -> None:
        """Notify all observers by calling their update method."""
        if not self._observers:
            return
        self._observers.notify()

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
    """Register `variable` as a dependency of the currently computing Computed."""
    stack = _COMPUTE_STACK
    if not stack:
        # Reads outside Computed evaluation do not participate in dependency tracking.
        return
    impl = stack[-1]
    owner = impl._owner
    if owner is variable:
        # Ignore self-reads to avoid self-dependency loops.
        return
    impl._dep_state.register_dependency(variable)


## Consider simplifying _has_changed.
# _VALUE_TYPES = {int, str, bytes, complex}


# def _has_changed(previous: Any, current: Any) -> bool:
#     if previous is current:
#         return False

#     value_type = type(previous)
#     if value_type is not type(current):
#         return True

#     if value_type is float:
#         return previous != current and not (math.isnan(previous) and math.isnan(current))

#     if value_type in _VALUE_TYPES:
#         return previous != current

#     return True


def _has_changed(previous: Any, current: Any) -> bool:
    """Best-effort change detection for assignments into reactive values.

    This function is intentionally fail-open: if comparison is ambiguous or
    raises, we treat the value as changed to avoid missing invalidations.
    """
    if previous is _BINDING_UNSET:
        return True

    previous_type = type(previous)
    current_type = type(current)
    if previous_type is current_type:
        if previous_type in {int, bool, str, bytes, complex, type(None)}:
            return previous != current
        if previous_type is float:
            return not (math.isnan(previous) and math.isnan(current)) and previous != current

    # Reactive wrappers compare by identity rather than their overloaded value
    # equality. Keep this after the scalar fast path: change detection runs for
    # every recomputed node, and most graph values are plain scalars.
    if _is_reactive_value(previous) or _is_reactive_value(current):
        return previous is not current

    # Compare callables by identity to avoid invoking custom `__eq__` logic and
    # to preserve stable references as unchanged.
    if callable(previous) or callable(current):
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

    - reading `value` returns the exact stored value
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

    def __init__(self, value: T) -> None:
        super().__init__()
        _setattr(self, "_value", value)
        if HOOKS_ENABLED:
            plugin_manager.hook.created(value=self)

    @property
    def value(self) -> T:
        """The current value.

        Getting this property returns the stored Python value. Setting it
        updates the stored value and notifies observers if the value changed.
        """
        if HOOKS_ENABLED:
            plugin_manager.hook.read(value=self)
        _track_read(self)
        return self._value

    @value.setter
    def value(self, new_value: T) -> None:
        old_value = self._value
        if _has_changed(old_value, new_value):
            _setattr(self, "_value", new_value)
            self._bump_version()
            if HOOKS_ENABLED:
                plugin_manager.hook.updated(value=self)
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
        before = self._value
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
        if HOOKS_ENABLED:
            plugin_manager.hook.updated(value=self)
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
    """Edge between a Computed consumer and one producer dependency.

    Links are reused across refreshes. ``seen_token`` records the refresh that
    last read this dependency and ``born_token`` the refresh that created the
    link, which is what lets commit and rollback both work as a single sweep.
    """

    __slots__ = ["dep", "version", "prev", "next", "active", "seen_token", "born_token"]

    def __init__(self, dep: Variable[Any], token: int) -> None:
        self.dep = dep
        self.version = -1
        self.prev: _DependencyLink | None = None
        self.next: _DependencyLink | None = None
        self.active = False
        self.seen_token = token
        self.born_token = token


class _PythonDependencyState:
    """Dependency bookkeeping as mark-and-sweep over one linked list.

    Each consumer keeps its dependency edges in insertion order, plus an index
    keyed by ``id()`` of the producer. Every refresh bumps a token; reads stamp
    their edge with it; ``commit_refresh`` walks the list once, subscribing to
    stamped edges and dropping unstamped ones.

    The index is safe to key on ``id()`` because a link holds its producer
    strongly for as long as the link is in the index.
    """

    __slots__ = ["_subscriber", "_head", "_tail", "_lookup", "_token"]

    def __init__(self, subscriber: Any) -> None:
        self._subscriber = subscriber
        self._head: _DependencyLink | None = None
        self._tail: _DependencyLink | None = None
        self._lookup: dict[int, _DependencyLink] = {}
        self._token = 0

    @property
    def deps(self) -> tuple[Variable[Any], ...]:
        deps: list[Variable[Any]] = []
        current = self._head
        while current is not None:
            deps.append(current.dep)
            current = current.next
        return tuple(deps)

    def start_refresh(self) -> None:
        self._token += 1

    def register_dependency(self, dependency: Variable[Any]) -> None:
        link = self._lookup.get(id(dependency))
        if link is None:
            link = _DependencyLink(dependency, self._token)
            self._lookup[id(dependency)] = link
            tail = self._tail
            link.prev = tail
            if tail is None:
                self._head = link
            else:
                tail.next = link
            self._tail = link
        else:
            link.seen_token = self._token

    def commit_refresh(self) -> None:
        """Subscribe to every dependency read this run and drop the rest."""
        token = self._token
        subscriber = self._subscriber
        link = self._head
        while link is not None:
            next_link = link.next
            if link.seen_token == token:
                if not link.active:
                    link.dep.subscribe(subscriber)
                    link.active = True
                link.version = link.dep._version
            else:
                self._detach(link)
            link = next_link

    def rollback_refresh(self) -> None:
        """Undo a failed run by dropping only the links it created.

        Links that predate the failed run keep their recorded versions, so the
        consumer stays subscribed to its previous dependencies and stale for
        retry.
        """
        token = self._token
        link = self._head
        while link is not None:
            next_link = link.next
            if link.born_token == token:
                self._detach(link)
            link = next_link

    def dependencies_changed(self) -> bool:
        link = self._head
        while link is not None:
            dep = link.dep
            if dep._IS_COMPUTED:
                dep._impl.ensure_uptodate()
            if link.version != dep._version:
                return True
            link = link.next
        return False

    def clear(self) -> None:
        link = self._head
        while link is not None:
            next_link = link.next
            link.active = False
            link.prev = None
            link.next = None
            link = next_link
        self._head = None
        self._tail = None
        self._lookup.clear()

    def _detach(self, link: _DependencyLink) -> None:
        """Unlink `link`, unsubscribe from its producer, and drop it from the index."""
        prev_link = link.prev
        next_link = link.next
        if prev_link is None:
            self._head = next_link
        else:
            prev_link.next = next_link
        if next_link is None:
            self._tail = prev_link
        else:
            next_link.prev = prev_link
        link.prev = None
        link.next = None
        del self._lookup[id(link.dep)]
        if link.active:
            link.dep.unsubscribe(self._subscriber)
            link.active = False


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
        _COMPUTE_STACK.append(self)
        try:
            next_value = owner._compute_fn()
        except BaseException:
            # Roll back: leave self._deps and self._state unchanged so the
            # Computed stays subscribed to its previous deps and remains stale
            # for retry on the next .value read.
            popped = _COMPUTE_STACK.pop()
            assert popped is self
            self._dep_state.rollback_refresh()
            self._is_computing = False
            raise
        popped = _COMPUTE_STACK.pop()
        assert popped is self
        self._is_computing = False

        # 2) Reconcile subscriptions against the dependency set from this run.
        self._dep_state.commit_refresh()

        # 3) Commit value/version if the computed result actually changed.
        self._state = _State.FRESH
        value_changed = not had_value or _has_changed(previous_value, next_value)
        if value_changed:
            _setattr(owner, "_value", next_value)
            self._global_version_seen = owner._bump_version()
            if HOOKS_ENABLED:
                plugin_manager.hook.updated(value=owner)
        elif forced_refresh:
            self._global_version_seen = owner._bump_version()
            if HOOKS_ENABLED:
                plugin_manager.hook.updated(value=owner)
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
        _setattr(self, "_compute_fn", f)
        _setattr(self, "_value", cast(T, None))  # placeholder; always set before read via _state guard
        _setattr(self, "_impl", _ComputedImpl(self))

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
        self._force_invalidate()

    def _force_invalidate(self) -> None:
        """Force refresh even when dependency versions appear unchanged."""
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
        return self._value


class Binding(Computed[T]):
    """A stable reactive handle whose current source can be replaced.

    Use a `Binding` when an object must keep the same public reactive identity
    while changing which `Signal`, `Computed`, or `Binding` supplies its value.
    Selecting a distinct source always invalidates downstream computations;
    `bind()` deliberately does not compare the old and new resolved values.

    Args:
        source: A reactive source to follow, or an initial plain value managed
            by a private `Signal`.
    """

    __slots__ = ("_owned", "_source")

    def __init__(self, source: T | ReactiveValue[T]) -> None:
        self._owned: Signal[T] | None
        if _is_reactive_value(source):
            self._source: ReactiveValue[T] = cast(ReactiveValue[T], source)
            self._owned = None
        else:
            owned = Signal(cast(T, source))
            self._owned = owned
            self._source = owned
        super().__init__(self._read_source)

    def _read_source(self) -> T:
        return self._source.value

    @Computed.value.setter
    def value(self, new_value: T) -> None:
        """Reject assignment; a binding selects a source rather than storing a value."""
        raise AttributeError(
            "Binding.value is read-only; use .set(value) for a plain value or .bind(source) for a reactive source"
        )

    @property
    def source(self) -> ReactiveValue[T]:
        """Return the exact current source without resolving it."""
        return self._source

    def bind(self, source: ReactiveValue[T]) -> Self:
        """Follow `source`, including its future value changes."""
        if source is self:
            raise ValueError("A Binding cannot bind itself")
        if not _is_reactive_value(source):
            raise TypeError("bind() requires a Signal, Computed, or Binding")
        if source is self._source:
            return self

        self._source = source
        # Source identity is the change. Clear the cached value so the lazy
        # refresh commits the new source's exact value even when it compares
        # equal to the previous source's value.
        _setattr(self, "_value", _BINDING_UNSET)
        self._force_invalidate()
        return self

    def set(self, value: T) -> Self:
        """Select and update this binding's private plain-value source."""
        if _is_reactive_value(value):
            raise TypeError("set() requires a plain value; use bind(source) for a reactive source")

        owned = self._owned
        if owned is None:
            owned = Signal(value)
            self._owned = owned
        else:
            owned.value = value

        return self.bind(owned)

    def derive(self, build: Callable[[ReactiveValue[T]], ReactiveValue[T]]) -> Self:
        """Build and select a source from the exact pre-rebind source.

        Capturing the old source prevents the common cycle created by building
        a new computation from the `Binding` that will receive that computation.
        """
        previous = self._source
        next_source = build(previous)
        if not _is_reactive_value(next_source):
            raise TypeError("derive() must return a Signal, Computed, or Binding")
        return self.bind(next_source)

    @contextmanager
    def at(self, value: T) -> Generator[None, None, None]:
        if _is_reactive_value(value):
            raise TypeError("at() requires a plain value. Use bind(source) for a reactive source.")

        previous = self._source
        temporary = Signal(value)
        try:
            self.bind(temporary)
            yield
        finally:
            self.bind(previous)


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

    __slots__ = ("_computed", "__weakref__")

    def __init__(self, fn: Callable[[], None]) -> None:
        self._computed = Computed(fn)
        self._computed.subscribe(self)  # triggers initial evaluation

    def update(self) -> None:
        """Called by a dependency when its value changes."""
        self._computed._impl.invalidate(force=True)
        self._computed._impl.ensure_uptodate()

    def dispose(self) -> None:
        """Unsubscribe from all dependencies and stop the effect."""
        self._computed.unsubscribe(self)
        for dep in tuple(self._computed._impl._deps):
            dep.unsubscribe(self._computed)
        self._computed._impl.clear_deps()
