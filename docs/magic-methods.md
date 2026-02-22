---
hide:
  - navigation
---
# Magic Methods and Operators

Signified exposes reactive behavior primarily through magic methods on `Signal` and `Computed`.

## Unary Methods

| Method | Usage example | Notes |
| --- | --- | --- |
| [`__abs__`](api.md#signified.core.ReactiveMixIn.__abs__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(-5)`<br>`#!pycon >>> abs(x)`<br>`#!pycon <5>` |  |
| [`__neg__`](api.md#signified.core.ReactiveMixIn.__neg__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> -x`<br>`#!pycon <-10>` |  |
| [`__pos__`](api.md#signified.core.ReactiveMixIn.__pos__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> +x`<br>`#!pycon <10>` |  |
| [`__invert__`](api.md#signified.core.ReactiveMixIn.__invert__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> flags = Signal(0b0011)`<br>`#!pycon >>> ~flags`<br>`#!pycon <-4>` |  |
| [`__round__`](api.md#signified.core.ReactiveMixIn.__round__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(3.14159)`<br>`#!pycon >>> round(x, 2)`<br>`#!pycon <3.14>` |  |
| [`__trunc__`](api.md#signified.core.ReactiveMixIn.__trunc__) | `#!pycon >>> import math`<br>`#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(3.9)`<br>`#!pycon >>> math.trunc(x)`<br>`#!pycon <3>` |  |
| [`__floor__`](api.md#signified.core.ReactiveMixIn.__floor__) | `#!pycon >>> import math`<br>`#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(3.9)`<br>`#!pycon >>> math.floor(x)`<br>`#!pycon <3>` |  |
| [`__ceil__`](api.md#signified.core.ReactiveMixIn.__ceil__) | `#!pycon >>> import math`<br>`#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(3.1)`<br>`#!pycon >>> math.ceil(x)`<br>`#!pycon <4>` |  |
| [`__str__`](api.md#signified.core.ReactiveMixIn.__str__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> str(x)`<br>`#!pycon '10'` | String conversion is **not** reactive. |

## Arithmetic and Bitwise Methods

| Method | Usage example | Notes |
| --- | --- | --- |
| [`__add__`](api.md#signified.core.ReactiveMixIn.__add__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a + b`<br>`#!pycon <13>` |  |
| [`__sub__`](api.md#signified.core.ReactiveMixIn.__sub__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a - b`<br>`#!pycon <7>` |  |
| [`__mul__`](api.md#signified.core.ReactiveMixIn.__mul__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a * b`<br>`#!pycon <30>` |  |
| [`__truediv__`](api.md#signified.core.ReactiveMixIn.__truediv__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a / b`<br>`#!pycon <3.3333333333333335>` |  |
| [`__floordiv__`](api.md#signified.core.ReactiveMixIn.__floordiv__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a // b`<br>`#!pycon <3>` |  |
| [`__mod__`](api.md#signified.core.ReactiveMixIn.__mod__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a % b`<br>`#!pycon <1>` |  |
| [`__pow__`](api.md#signified.core.ReactiveMixIn.__pow__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a ** b`<br>`#!pycon <1000>` |  |
| [`__divmod__`](api.md#signified.core.ReactiveMixIn.__divmod__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> divmod(a, b)`<br>`#!pycon <(3, 1)>` |  |
| [`__matmul__`](api.md#signified.core.ReactiveMixIn.__matmul__) | `#!pycon >>> import numpy as np`<br>`#!pycon >>> from signified import Signal`<br>`#!pycon >>> left = Signal(np.array([1, 2]))`<br>`#!pycon >>> right = Signal(np.array([1, 1]))`<br>`#!pycon >>> left @ right`<br>`#!pycon <3>` |  |
| [`__and__`](api.md#signified.core.ReactiveMixIn.__and__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(0b1100)`<br>`#!pycon >>> b = Signal(0b1010)`<br>`#!pycon >>> a & b`<br>`#!pycon <8>` |  |
| [`__or__`](api.md#signified.core.ReactiveMixIn.__or__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(0b1100)`<br>`#!pycon >>> b = Signal(0b1010)`<br>`#!pycon >>> a | b`<br>`#!pycon <14>` |  |
| [`__xor__`](api.md#signified.core.ReactiveMixIn.__xor__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(0b1100)`<br>`#!pycon >>> b = Signal(0b1010)`<br>`#!pycon >>> a ^ b`<br>`#!pycon <6>` |  |
| [`__lshift__`](api.md#signified.core.ReactiveMixIn.__lshift__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> x << 1`<br>`#!pycon <20>` |  |
| [`__rshift__`](api.md#signified.core.ReactiveMixIn.__rshift__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> x >> 1`<br>`#!pycon <5>` |  |

## Reverse Arithmetic and Bitwise Methods

| Method | Usage example | Notes |
| --- | --- | --- |
| [`__radd__`](api.md#signified.core.ReactiveMixIn.__radd__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 5 + x`<br>`#!pycon <15>` |  |
| [`__rsub__`](api.md#signified.core.ReactiveMixIn.__rsub__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 50 - x`<br>`#!pycon <40>` |  |
| [`__rmul__`](api.md#signified.core.ReactiveMixIn.__rmul__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 5 * x`<br>`#!pycon <50>` |  |
| [`__rtruediv__`](api.md#signified.core.ReactiveMixIn.__rtruediv__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 50 / x`<br>`#!pycon <5.0>` |  |
| [`__rfloordiv__`](api.md#signified.core.ReactiveMixIn.__rfloordiv__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 50 // x`<br>`#!pycon <5>` |  |
| [`__rmod__`](api.md#signified.core.ReactiveMixIn.__rmod__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 50 % x`<br>`#!pycon <0>` |  |
| [`__rpow__`](api.md#signified.core.ReactiveMixIn.__rpow__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> 2 ** x`<br>`#!pycon <1024>` |  |
| [`__rdivmod__`](api.md#signified.core.ReactiveMixIn.__rdivmod__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> divmod(50, x)`<br>`#!pycon <(5, 0)>` |  |
| [`__rand__`](api.md#signified.core.ReactiveMixIn.__rand__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(0b0101)`<br>`#!pycon >>> 0b1111 & x`<br>`#!pycon <5>` |  |
| [`__ror__`](api.md#signified.core.ReactiveMixIn.__ror__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(0b0101)`<br>`#!pycon >>> 0b1111 | x`<br>`#!pycon <15>` |  |
| [`__rxor__`](api.md#signified.core.ReactiveMixIn.__rxor__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(0b0101)`<br>`#!pycon >>> 0b1111 ^ x`<br>`#!pycon <10>` |  |

## Comparisons, Predicates, and Truthiness

For operations that Python cannot overload cleanly (`is`, `is not`, and
truthiness via `bool(...)`) or that have special semantics in Signified
(`==`), use the `rx` namespace (`x.rx.*`). Legacy direct methods like
`x.eq(...)` still work, but are deprecated aliases.

| Method | Usage example | Notes |
| --- | --- | --- |
| [`__lt__`](api.md#signified.core.ReactiveMixIn.__lt__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a < b`<br>`#!pycon <False>` |  |
| [`__le__`](api.md#signified.core.ReactiveMixIn.__le__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a <= b`<br>`#!pycon <False>` |  |
| [`__gt__`](api.md#signified.core.ReactiveMixIn.__gt__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a > b`<br>`#!pycon <True>` |  |
| [`__ge__`](api.md#signified.core.ReactiveMixIn.__ge__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a >= b`<br>`#!pycon <True>` |  |
| [`__ne__`](api.md#signified.core.ReactiveMixIn.__ne__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a != b`<br>`#!pycon <True>` |  |
| [`rx.is_`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> marker = object()`<br>`#!pycon >>> s = Signal(marker)`<br>`#!pycon >>> s.rx.is_(marker)`<br>`#!pycon <True>` | `is` is not overloadable. Use this for reactive identity checks. |
| [`rx.is_not`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> maybe_user = Signal(None)`<br>`#!pycon >>> maybe_user.rx.is_not(None)`<br>`#!pycon <False>` | `is not` is not overloadable. |
| [`rx.eq`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> a = Signal(10)`<br>`#!pycon >>> b = Signal(3)`<br>`#!pycon >>> a.rx.eq(b)`<br>`#!pycon <False>` | `__eq__` is intentionally not overloaded; use `rx.eq` for reactive equality. |
| [`rx.in_`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> needle = Signal(2)`<br>`#!pycon >>> haystack = Signal([1, 2, 3])`<br>`#!pycon >>> needle.rx.in_(haystack)`<br>`#!pycon <True>` |  |
| [`rx.contains`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> nums = Signal([1, 2, 3])`<br>`#!pycon >>> nums.rx.contains(2)`<br>`#!pycon <True>` | |
| [`rx.where`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> flag = Signal(True)`<br>`#!pycon >>> flag.rx.where("yes", "no")`<br>`#!pycon <yes>` |  |
| [`rx.as_bool`](api.md#signified.core.ReactiveMixIn.rx) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> x = Signal(10)`<br>`#!pycon >>> x.rx.as_bool()`<br>`#!pycon <True>` | `__bool__` cannot safely be reactive because Python expects an immediate bool in control flow. |

## Object and Container Access

| Method | Usage example | Notes |
| --- | --- | --- |
| [`__getattr__`](api.md#signified.core.ReactiveMixIn.__getattr__) | `#!pycon >>> from types import SimpleNamespace`<br>`#!pycon >>> from signified import Signal`<br>`#!pycon >>> person = Signal(SimpleNamespace(name="Alice"))`<br>`#!pycon >>> person.name`<br>`#!pycon <Alice>` |  |
| [`__call__`](api.md#signified.core.ReactiveMixIn.__call__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> fn = Signal(lambda x: x + 1)`<br>`#!pycon >>> fn(10)`<br>`#!pycon <11>` |  |
| [`__getitem__`](api.md#signified.core.ReactiveMixIn.__getitem__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> Signal([1, 2, 3])[1]`<br>`#!pycon <2>`<br>`#!pycon >>> Signal({"x": 1})["x"]`<br>`#!pycon <1>` |  |
| [`__setattr__`](api.md#signified.core.ReactiveMixIn.__setattr__) | `#!pycon >>> from types import SimpleNamespace`<br>`#!pycon >>> from signified import Signal`<br>`#!pycon >>> person = Signal(SimpleNamespace(name="Alice"))`<br>`#!pycon >>> name = person.name`<br>`#!pycon >>> person.name = "Bob"`<br>`#!pycon >>> name`<br>`#!pycon <Bob>` | Updates wrapped object attributes and notifies dependents. |
| [`__setitem__`](api.md#signified.core.ReactiveMixIn.__setitem__) | `#!pycon >>> from signified import Signal`<br>`#!pycon >>> nums = Signal([1, 2, 3])`<br>`#!pycon >>> first = nums[0]`<br>`#!pycon >>> nums[0] = 10`<br>`#!pycon >>> first`<br>`#!pycon <10>` | Works for wrapped `list`/`dict` item updates. |

## Complete API Reference

See [Core API](api.md) for full signatures, overloads, and docstring examples.
