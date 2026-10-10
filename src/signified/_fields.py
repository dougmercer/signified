"""Attributes whose reassignment is tracked by the reactive graph."""

from __future__ import annotations

import dataclasses
from types import MemberDescriptorType
from typing import Any, Callable, overload

from ._core import is_tracking
from ._reactive import Signal

__all__ = ["tracked_fields"]

_MISSING: Any = object()


def _stored_value(value: Any) -> Any:
    """Rebuild a field's stored value when a hidden source is pickled."""
    return value


class _FieldSource(Signal[Any]):
    """Hidden per-instance signal holding one tracked field's stored value.

    It is created on the first tracked read, so objects that are never read
    inside a computation carry no extra nodes. `_owner_id` identifies the
    instance it belongs to: a shallow copy of an instance dict shares the
    source object, and the copy must not write through it.
    """

    __slots__ = ("_owner_id",)
    _WARN_ON_VALUE = False  # Storing reactive objects here is intentional.

    def __init__(self, value: Any, owner: object) -> None:
        super().__init__(value)
        self._owner_id = id(owner)

    # Copies and pickles of an instance carry the stored value, not the node.
    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        from copy import deepcopy

        return deepcopy(self._value, memo)

    def __reduce__(self) -> tuple[Callable[[Any], Any], tuple[Any]]:
        return _stored_value, (self._value,)


class _TrackedField:
    """Data descriptor that tracks reads and reassignment of one attribute.

    The stored value lives where it would without the descriptor: in the
    class's slot, or in the instance dict. Until a computation reads the field,
    that storage holds the plain stored value. The first tracked read replaces
    it with a `_FieldSource` holding the same value.
    """

    __slots__ = ("_name", "_get", "_set", "_default")

    def __init__(self, name: str, slot: MemberDescriptorType | None, default: Any) -> None:
        self._name = name
        self._default = default
        if slot is not None:
            self._get = slot.__get__
            self._set = slot.__set__
        else:
            self._get = self._get_from_dict
            self._set = self._set_in_dict

    def _get_from_dict(self, obj: Any) -> Any:
        try:
            return obj.__dict__[self._name]
        except KeyError:
            if self._default is _MISSING:
                raise AttributeError(f"'{type(obj).__name__}' object has no attribute '{self._name}'") from None
            return self._default

    def _set_in_dict(self, obj: Any, value: Any) -> None:
        obj.__dict__[self._name] = value

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        stored = self._get(obj)
        if not is_tracking():
            return stored._value if type(stored) is _FieldSource else stored
        if type(stored) is not _FieldSource or stored._owner_id != id(obj):
            value = stored._value if type(stored) is _FieldSource else stored
            stored = _FieldSource(value, obj)
            self._set(obj, stored)
        return stored.value

    def __set__(self, obj: Any, value: Any) -> None:
        try:
            stored = self._get(obj)
        except AttributeError:
            stored = None
        if type(stored) is _FieldSource and stored._owner_id == id(obj):
            stored.value = value
        else:
            self._set(obj, value)

    def __delete__(self, obj: Any) -> None:
        raise AttributeError(f"tracked field '{self._name}' cannot be deleted")


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

    Reads outside a computation skip the graph, but still cost a Python
    descriptor call. In-place mutation of a stored object is not observed.

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

    for name in names:
        existing = _lookup(cls, name)
        if isinstance(existing, _TrackedField):
            continue
        slot = existing if type(existing) is MemberDescriptorType else None
        if slot is None and existing is not _MISSING and hasattr(type(existing), "__get__"):
            raise TypeError(f"'{cls.__name__}.{name}' is already a descriptor and cannot be tracked")
        default = _MISSING if slot is not None else existing
        setattr(cls, name, _TrackedField(name, slot, default))
    return cls


def _lookup(cls: type, name: str) -> Any:
    """Return the class attribute `name` without invoking descriptors, or `_MISSING`."""
    for base in cls.__mro__:
        if name in base.__dict__:
            return base.__dict__[name]
    return _MISSING
