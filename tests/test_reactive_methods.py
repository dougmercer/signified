import math

from signified import Signal, batch


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
    assert s1.rx.eq(s2).value == False  # noqa: E712
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

    assert s.rx.contains(3).value == True  # noqa: E712
    assert s.rx.contains(6).value == False  # noqa: E712


def test_signal_bool():
    """Test boolean evaluation of Signal."""
    s1 = Signal(1)
    s2 = Signal(0)
    s3 = Signal([])
    s4 = Signal([1, 2, 3])

    assert s1.rx.as_bool().value == True  # noqa: E712
    assert s2.rx.as_bool().value == False  # noqa: E712
    assert s3.rx.as_bool().value == False  # noqa: E712
    assert s4.rx.as_bool().value == True  # noqa: E712


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

    result = condition.rx.where(s1, s2)
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


def test_signal_rx_map_is_lazy():
    """Test that signal.rx.map does not execute until read."""
    runs = 0
    s = Signal(2)

    def mapper(value: int) -> int:
        nonlocal runs
        runs += 1
        return value * 2

    doubled = s.rx.map(mapper)

    assert runs == 0
    s.value = 5
    assert runs == 0
    assert doubled.value == 10
    assert runs == 1


def test_signal_rx_peek():
    """Test side effects via signal.rx.peek."""
    seen: list[int] = []
    s = Signal(1)
    passthrough = s.rx.peek(lambda x: seen.append(x))

    assert passthrough.value == 1
    s.value = 3
    assert passthrough.value == 3
    assert seen == [1, 3]


def test_signal_rx_peek_is_lazy_and_skips_intermediate_updates():
    """Test lazy read semantics for signal.rx.peek."""
    seen: list[int] = []
    s = Signal(1)
    passthrough = s.rx.peek(seen.append)

    assert seen == []
    s.value = 2
    s.value = 3
    assert seen == []
    assert passthrough.value == 3
    assert seen == [3]


def test_signal_rx_effect_runs_immediately_and_on_updates():
    """Test eager side effects via signal.rx.effect."""
    seen: list[int] = []
    s = Signal(1)

    effect = s.rx.effect(seen.append)

    assert seen == [1]
    s.value = 2
    s.value = 3
    assert seen == [1, 2, 3]
    effect.dispose()


def test_signal_rx_effect_dispose_unsubscribes():
    """Test that disposing signal.rx.effect stops future callbacks."""
    seen: list[int] = []
    s = Signal(1)

    effect = s.rx.effect(seen.append)
    effect.dispose()

    s.value = 99
    assert seen == [1]


def test_effect_auto_tracks_multiple_sources():
    """Effect re-runs when any reactive value read inside fn changes."""
    from signified import Effect

    a = Signal(1)
    b = Signal(10)
    results: list[int] = []

    e = Effect(lambda: results.append(a.value + b.value))
    assert results == [11]

    a.value = 2
    assert results == [11, 12]

    b.value = 20  # was only tracked by old single-source Effect; now works
    assert results == [11, 12, 22]

    e.dispose()


def test_effect_dynamic_deps_follow_branch():
    """Effect drops deps from inactive branch, just like Computed."""
    from signified import Effect

    flag = Signal(True)
    a = Signal("left")
    b = Signal("right")
    seen: list[str] = []

    e = Effect(lambda: seen.append(a.value if flag.value else b.value))
    assert seen == ["left"]

    b.value = "RIGHT"  # not tracked while flag is True
    assert seen == ["left"]

    flag.value = False  # switches branch; a dropped, b picked up
    assert seen == ["left", "RIGHT"]

    a.value = "LEFT_UPDATED"  # a is now dropped
    assert seen == ["left", "RIGHT"]

    b.value = "RIGHT2"
    assert seen == ["left", "RIGHT", "RIGHT2"]

    e.dispose()


def test_effect_dispose_stops_all_tracked_deps():
    """dispose() unsubscribes from every dep, including dynamically added ones."""
    from signified import Effect

    a = Signal(1)
    b = Signal(2)
    results: list[int] = []

    e = Effect(lambda: results.append(a.value + b.value))
    assert results == [3]

    e.dispose()
    a.value = 99
    b.value = 99
    assert results == [3]  # no new calls after dispose


def test_batch_coalesces_effect_reruns_until_exit():
    from signified import Effect

    left = Signal(1)
    right = Signal(2)
    seen: list[int] = []

    effect = Effect(lambda: seen.append(left.value + right.value))

    assert seen == [3]

    with batch():
        left.value = 10
        right.value = 20
        assert seen == [3]

    assert seen == [3, 30]
    effect.dispose()


def test_disposed_effect_does_not_run_when_batch_flushes():
    from signified import Effect

    source = Signal(1)
    seen: list[int] = []

    effect = Effect(lambda: seen.append(source.value))
    assert seen == [1]

    with batch():
        source.value = 2
        effect.dispose()

    assert seen == [1]


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
