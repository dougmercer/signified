from signified import Signal, Computed, computed


def test_computed_basic():
    """Test basic Computed functionality."""
    s = Signal(5)
    c = Computed(lambda: s.value * 2, dependencies=[s])

    assert c.value == 10

    s.value = 7
    assert c.value == 14


def test_computed_decorator():
    """Test the @computed decorator."""
    s = Signal(5)

    @computed
    def double_it(x):
        return x * 2

    c = double_it(s)
    assert c.value == 10

    s.value = 7
    assert c.value == 14


def test_computed_dependencies():
    """Test Computed with multiple dependencies."""
    s1 = Signal(5)
    s2 = Signal(10)

    @computed
    def add_em(a, b):
        return a + b

    c = add_em(s1, s2)
    assert c.value == 15

    s1.value = 7
    assert c.value == 17

    s2.value = 13
    assert c.value == 20


def test_computed_with_nested_signals():
    """Test Computed with multiple nested Signals."""
    s1 = Signal(Signal(5))
    s2 = Signal(Signal(Signal(3)))

    @computed
    def complex_computation(a, b):
        return a * b

    result = complex_computation(s1, s2)
    assert result.value == 15

    s1.value = 7
    assert result.value == 21


def test_computed_chaining():
    """Test chaining of Computed values."""
    s = Signal(5)
    c1 = computed(lambda x: x * 2)(s)
    c2 = computed(lambda x: x + 3)(c1)

    assert c2.value == 13
    s.value = 10
    assert c2.value == 23
