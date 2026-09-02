import pytest

from signified import Binding, Computed, Signal, as_rx, computed, effect, unref


def test_binding_follows_current_source_and_rebinds() -> None:
    first = Signal(1)
    second = Signal(10)
    binding = Binding(first)
    derived = computed(lambda value: value * 2)(binding)

    assert binding.source is first
    assert derived.value == 2
    first.value = 2
    assert derived.value == 4

    assert binding.bind(second) is binding
    assert binding.source is second
    assert derived.value == 20
    first.value = 3
    assert derived.value == 20
    second.value = 11
    assert derived.value == 22


def test_binding_of_binding_follows_rebinding() -> None:
    first = Signal(1)
    inner = Binding(first)
    outer = Binding(inner)

    assert outer.value == 1
    inner.bind(Signal(2))
    assert outer.value == 2


def test_binding_distinct_equal_source_forces_direct_dependent_recompute() -> None:
    binding = Binding(Signal(1))
    runs = 0

    def read(value: int) -> int:
        nonlocal runs
        runs += 1
        return value

    derived = computed(read)(binding)
    assert derived.value == 1
    assert runs == 1

    binding.bind(Signal(1))
    assert derived.value == 1
    assert runs == 2


def test_binding_rebind_does_not_compare_resolved_values() -> None:
    class EqualityMustNotRun:
        def __eq__(self, other: object) -> bool:
            raise AssertionError("Binding.bind must not compare resolved values")

    binding = Binding(Signal(EqualityMustNotRun()))
    _ = binding.value

    binding.bind(Signal(EqualityMustNotRun()))
    _ = binding.value


def test_binding_same_source_is_a_noop() -> None:
    source = Signal(1)
    binding = Binding(source)
    runs = 0

    def read() -> int:
        nonlocal runs
        runs += 1
        return binding.value

    derived = Computed(read)
    assert derived.value == 1
    binding.bind(source)
    assert derived.value == 1
    assert runs == 1


def test_binding_set_uses_private_plain_source() -> None:
    external = Signal(1)
    binding = Binding(external)

    assert binding.set(5) is binding
    private_source = binding.source
    assert isinstance(private_source, Signal)
    assert private_source is not external
    assert binding.value == 5

    external.value = 2
    assert binding.value == 5
    binding.set(6)
    assert binding.source is private_source
    assert binding.value == 6


def test_binding_plain_constructor_value_can_be_set() -> None:
    binding = Binding(1)
    source = binding.source

    binding.set(2)
    assert binding.source is source
    assert binding.value == 2


def test_binding_derive_captures_pre_rebind_source() -> None:
    base = Signal(2)
    binding = Binding(base)

    binding.derive(lambda previous: computed(lambda value: value * 3)(previous))

    assert binding.value == 6
    base.value = 4
    assert binding.value == 12


def test_binding_derive_failure_leaves_source_unchanged() -> None:
    source = Signal(1)
    binding = Binding(source)

    with pytest.raises(TypeError, match="derive"):
        binding.derive(lambda previous: previous.value + 1)  # type: ignore[arg-type, return-value]

    assert binding.source is source


def test_binding_at_restores_exact_source_with_nested_contexts() -> None:
    source = Signal(1)
    binding = Binding(source)

    with binding.at(2):
        first_temporary = binding.source
        assert binding.value == 2
        with binding.at(3):
            assert binding.value == 3
        assert binding.source is first_temporary
        assert binding.value == 2

    assert binding.source is source
    assert binding.value == 1


def test_binding_rejects_invalid_sources() -> None:
    binding = Binding(1)

    with pytest.raises(TypeError, match="bind"):
        binding.bind(2)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot bind itself"):
        binding.bind(binding)


def test_binding_cycle_raises_on_read() -> None:
    binding = Binding(1)
    cyclic = Computed(lambda: binding.value + 1)
    binding.bind(cyclic)

    with pytest.raises(RuntimeError, match="Cycle detected"):
        _ = binding.value


def test_computed_can_return_reactive_result() -> None:
    source = Signal(1)
    result = Computed(lambda: source)

    assert result.value is source


def test_binding_integrates_with_effect_unref_and_as_rx() -> None:
    binding = Binding(Signal(1))
    seen: list[int] = []
    watcher = effect(seen.append)(binding)

    assert unref(binding) == 1
    assert as_rx(binding) is binding
    binding.bind(Signal(2))
    assert seen == [1, 2]
    watcher.dispose()


def test_binding_at_restores_across_sequential_contexts() -> None:
    source = Signal(1)
    binding = Binding(source)

    with binding.at(2):
        assert binding.value == 2
    assert binding.value == 1
    assert binding.source is source

    with binding.at(3):
        assert binding.value == 3
    assert binding.value == 1
    assert binding.source is source


def test_binding_at_nests_three_deep() -> None:
    frame = Signal(0)
    animated = computed(lambda value: value * 2)(frame)
    binding = Binding(animated)
    seen: list[int] = []

    with binding.at(1):
        seen.append(binding.value)
        with binding.at(2):
            seen.append(binding.value)
            with binding.at(3):
                seen.append(binding.value)
            seen.append(binding.value)
        seen.append(binding.value)

    assert seen == [1, 2, 3, 2, 1]
    assert binding.source is animated

    frame.value = 3
    assert binding.value == 6


def test_binding_value_is_read_only() -> None:
    binding = Binding(Signal(1))

    with pytest.raises(AttributeError, match=r"read-only.*\.set\(value\).*\.bind\(source\)"):
        binding.value = 5

    assert binding.value == 1
