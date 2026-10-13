"""Attributes whose reassignment is tracked by the reactive graph."""

from __future__ import annotations

import dataclasses
from types import MemberDescriptorType
from typing import Any, Callable, overload

from ._core import FieldSource, TrackedField
from ._reactive import Signal

__all__ = ["tracked_fields"]

_MISSING: Any = object()


def _stored_value(value: Any) -> Any:
    """Rebuild a field's stored value when a hidden source is pickled."""
    return value


class _FieldSource(FieldSource, Signal[Any]):
    """Hidden per-instance signal holding one tracked field's stored value.

    It is created on the first tracked read, so objects that are never read
    inside a computation carry no extra nodes. The native base records the
    instance it belongs to: a shallow copy of an instance dict shares the
    source object, and the copy must not write through it.
    """

    __slots__ = ()

    # Copies and pickles of an instance carry the stored value, not the node.
    def __copy__(self) -> Any:
        return self._value

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        from copy import deepcopy

        return deepcopy(self._value, memo)

    def __reduce__(self) -> tuple[Callable[[Any], Any], tuple[Any]]:
        return _stored_value, (self._value,)


@overload
def tracked_fields[C: type](cls: C, /) -> C: ...


@overload
def tracked_fields[C: type](*names: str) -> Callable[[C], C]: ...


def tracked_fields(*args: Any) -> Any:
    """Track reads and reassignment of a class's attributes.

    Reading a tracked attribute returns exactly what was stored: a plain value,
    or the `Signal`, `Computed`, or `Binding` that was assigned. It never
    unwraps. Inside a computation or effect, the read also depends on the
    attribute itself, so assigning a new value invalidates the reader. Use
    [unref][signified.unref] as usual to read through a stored reactive value.

    Assignment uses the usual change rule: built-in scalars compare by value,
    other objects by identity. Assigning a reactive value replaces the stored
    one; it never writes into the previously stored signal.

    Apply it above `@dataclass` to track every field, or pass names to track
    only those. Names are required for a class that is not a dataclass. Both
    slotted and dict-based classes work; frozen dataclasses are rejected.
    Copies and pickles store plain values and get their own tracking.

    Reads outside a computation skip the graph, but still cost a descriptor
    call. In-place mutation of a stored object is not observed.

    Example:
        ```py
        >>> from dataclasses import dataclass
        >>> from signified import HasValue, unref
        >>> @tracked_fields
        ... @dataclass(slots=True)
        ... class Material:
        ...     roughness: HasValue[float] = 0.5
        >>> material = Material()
        >>> doubled = Computed(lambda: unref(material.roughness) * 2)
        >>> doubled.value
        1.0
        >>> material.roughness = 0.25
        >>> doubled.value
        0.5
        >>> material.roughness = Signal(0.1)
        >>> doubled.value
        0.2

        ```
    """
    if len(args) == 1 and isinstance(args[0], type):
        return _install(args[0], None)
    for name in args:
        if not isinstance(name, str):
            raise TypeError("tracked_fields() takes a class or attribute names")
    names = tuple(args)
    return lambda cls: _install(cls, names)


def _install[C: type](cls: C, names: tuple[str, ...] | None) -> C:
    params = cls.__dict__.get("__dataclass_params__") or getattr(cls, "__dataclass_params__", None)
    if params is not None:
        if params.frozen:
            raise TypeError("tracked_fields() cannot track a frozen dataclass")
        if names is None:
            names = tuple(field.name for field in dataclasses.fields(cls))
    elif names is None:
        raise TypeError("tracked_fields() needs attribute names for a class that is not a dataclass")

    in_dict = False
    for name in names:
        existing = _lookup(cls, name)
        if isinstance(existing, TrackedField):
            continue
        slot = existing if type(existing) is MemberDescriptorType else None
        if slot is None and existing is not _MISSING and hasattr(type(existing), "__get__"):
            raise TypeError(f"'{cls.__name__}.{name}' is already a descriptor and cannot be tracked")
        default = () if slot is not None or existing is _MISSING else (existing,)
        setattr(cls, name, TrackedField(name, slot, _FieldSource, *default))
        in_dict = in_dict or slot is None
    if in_dict:
        _copy_stored_values(cls)
    return cls


def _copy_stored_values(cls: type) -> None:
    """Make copies and pickles of `cls` instances hold plain values, not sources.

    By default an instance's state is its dict itself, so a shallow copy would
    share each field's source and keep following the original.
    """
    getstate: Callable[[Any], Any] = getattr(cls, "__getstate__")

    def __getstate__(self: Any) -> Any:
        return _without_sources(getstate(self))

    setattr(cls, "__getstate__", __getstate__)


def _without_sources(state: Any) -> Any:
    """Replace sources in an instance's state, its dict or a `(dict, slots)` pair, with their values."""
    if isinstance(state, dict):
        return {name: value._value if type(value) is _FieldSource else value for name, value in state.items()}
    if isinstance(state, tuple) and len(state) == 2 and isinstance(state[0], dict):
        return (_without_sources(state[0]), state[1])
    return state


def _lookup(cls: type, name: str) -> Any:
    """Return the class attribute `name` without invoking descriptors, or `_MISSING`."""
    for base in cls.__mro__:
        if name in base.__dict__:
            return base.__dict__[name]
    return _MISSING
