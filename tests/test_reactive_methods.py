import math

import pytest

from signified import Signal


def test_signal_arithmetic():
    """Test Signal arithmetic operations."""
    s1 = Signal(5)
    s2 = Signal(10)

    sum_computed = s1 + s2
    assert sum_computed.value == 15

    s1.value = 7
    assert sum_computed.value == 17


def test_signal_comparison():
    """Test Signal comparison operations."""
    s1 = Signal(5)
    s2 = Signal(10)

    gt_computed = s2 > s1
    assert gt_computed.value == True  # noqa: E712

    s1.value = 15
    assert gt_computed.value == False  # noqa: E712


def test_signal_arithmetic_operations():
    """Test various arithmetic operations on Signals."""
    s1 = Signal(5)
    s2 = Signal(3)

    assert (s1 + s2).value == 8
    assert (s1 - s2).value == 2
    assert (s1 * s2).value == 15
    assert (s1 / s2).value == 5 / 3
    assert (s1 // s2).value == 1
    assert (s1 % s2).value == 2
    assert (s1**s2).value == 125


def test_signal_comparison_operations():
    """Test comparison operations on Signals."""
    s1 = Signal(5)
    s2 = Signal(3)

    assert (s1 > s2).value == True  # noqa: E712
    assert (s1 >= s2).value == True  # noqa: E712
    assert (s1 < s2).value == False  # noqa: E712
    assert (s1 <= s2).value == False  # noqa: E712
    assert s1.eq(s2).value == False  # noqa: E712
    assert (s1 != s2).value == True  # noqa: E712


def test_signal_boolean_operations():
    """Test boolean operations on Signals."""
    s1 = Signal(True)
    s2 = Signal(False)

    assert (s1 & s2).value == False  # noqa: E712
    assert (s1 | s2).value == True  # noqa: E712
    assert (s1 ^ s2).value == True  # noqa: E712
    assert (s1 ^ s1).value == False  # noqa: E712


def test_signal_bitwise_operations():
    """Test bitwise operations on Signals."""
    s1 = Signal(0b0101)  # 5 in binary
    s2 = Signal(0b0011)  # 3 in binary

    assert (s1 & s2).value == 0b0001  # Bitwise AND
    assert (s1 | s2).value == 0b0111  # Bitwise OR
    assert (s1 ^ s2).value == 0b0110  # Bitwise XOR
    assert (~s1).value == ~0b0101  # Bitwise NOT
    assert (s1 << 1).value == 0b1010  # Left shift
    assert (s1 >> 1).value == 0b0010  # Right shift


def test_signal_inplace_operations():
    """Test in-place operations on Signals."""
    s = Signal(5)

    s.value += 3
    assert s.value == 8

    s.value *= 2
    assert s.value == 16

    s.value //= 3
    assert s.value == 5


def test_signal_attribute_access():
    """Test attribute access on Signal containing an object."""

    class MyObj:
        def __init__(self):
            self.x = 5
            self.y = 10

    s = Signal(MyObj())

    assert s.x.value == 5
    assert s.y.value == 10


def test_signal_method_call():
    """Test method calls on Signal containing an object."""

    class MyObj:
        def __init__(self, value):
            self.value = value

        def double(self):
            return self.value * 2

    s = Signal(MyObj(5))

    assert s.double().value == 10


def test_signal_indexing():
    """Test indexing on Signal containing a sequence."""
    s = Signal([1, 2, 3, 4, 5])

    assert s[0].value == 1
    assert s[-1].value == 5
    assert s[1:4].value == [2, 3, 4]


def test_signal_contains():
    """Test 'in' operator on Signal containing a sequence."""
    s = Signal([1, 2, 3, 4, 5])

    assert s.contains(3).value == True  # noqa: E712
    assert s.contains(6).value == False  # noqa: E712


def test_signal_bool():
    """Test boolean evaluation of Signal."""
    s1 = Signal(1)
    s2 = Signal(0)
    s3 = Signal([])
    s4 = Signal([1, 2, 3])

    assert s1.as_bool().value == True  # noqa: E712
    assert s2.as_bool().value == False  # noqa: E712
    assert s3.as_bool().value == False  # noqa: E712
    assert s4.as_bool().value == True  # noqa: E712


def test_signal_math_functions():
    """Test math functions on Signals."""
    s = Signal(15.1)

    assert math.ceil(s).value == 16
    assert math.floor(s).value == 15
    assert round(s).value == 15
    assert abs(s).value == 15.1

    s.value = -15.1
    assert abs(s).value == 15.1


def test_signal_where():
    """Test the 'where' method on Signals."""
    condition = Signal(True)
    s1 = Signal(5)
    s2 = Signal(10)

    result = condition.where(s1, s2)
    assert result.value == 5

    condition.value = False
    assert result.value == 10


def test_signal_rx_map():
    """Test reactive transforms via signal.rx.map."""
    s = Signal(2)
    doubled = s.rx.map(lambda x: x * 2)

    assert doubled.value == 4
    s.value = 5
    assert doubled.value == 10


def test_signal_rx_tap():
    """Test side effects via signal.rx.tap."""
    seen: list[int] = []
    s = Signal(1)
    passthrough = s.rx.tap(lambda x: seen.append(x))

    assert passthrough.value == 1
    s.value = 3
    assert passthrough.value == 3
    assert seen == [1, 3]


def test_signal_rx_len():
    """Test reactive length via signal.rx.len."""
    values = Signal([1, 2, 3])
    length = values.rx.len()

    assert length.value == 3
    values.value = [1]
    assert length.value == 1


def test_signal_rx_identity_methods():
    """Test reactive identity checks via signal.rx.is_ / signal.rx.is_not."""
    marker = object()
    s = Signal(marker)

    assert s.rx.is_(marker).value == True  # noqa: E712
    assert s.rx.is_not(marker).value == False  # noqa: E712

    other = object()
    s.value = other
    assert s.rx.is_(marker).value == False  # noqa: E712
    assert s.rx.is_not(marker).value == True  # noqa: E712


def test_signal_rx_eq():
    """Test reactive equality via signal.rx.eq."""
    s = Signal(10)
    result = s.rx.eq(10)

    assert result.value == True  # noqa: E712
    s.value = 25
    assert result.value == False  # noqa: E712


def test_signal_rx_in():
    """Test reverse containment via signal.rx.in_."""
    needle = Signal(2)
    haystack = Signal([1, 2, 3])
    result = needle.rx.in_(haystack)

    assert result.value == True  # noqa: E712
    needle.value = 4
    assert result.value == False  # noqa: E712
    haystack.value = [4, 5]
    assert result.value == True  # noqa: E712


def test_legacy_non_dunder_methods_emit_deprecation_warning():
    """Test that legacy non-dunder methods warn and still function."""
    s = Signal([1, 2, 3])

    with pytest.warns(DeprecationWarning, match=r"ReactiveMixIn\.as_bool"):
        assert Signal(1).as_bool().value == True  # noqa: E712

    with pytest.warns(DeprecationWarning, match=r"ReactiveMixIn\.contains"):
        assert s.contains(2).value == True  # noqa: E712

    with pytest.warns(DeprecationWarning, match=r"ReactiveMixIn\.is_not"):
        assert Signal(1).is_not(None).value == True  # noqa: E712

    with pytest.warns(DeprecationWarning, match=r"ReactiveMixIn\.eq"):
        assert Signal(2).eq(2).value == True  # noqa: E712

    with pytest.warns(DeprecationWarning, match=r"ReactiveMixIn\.where"):
        assert Signal(True).where("a", "b").value == "a"
