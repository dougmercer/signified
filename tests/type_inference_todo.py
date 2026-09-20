"""Known typing gaps for signified's public API.

To evaluate progress toward desired inference:
1. Change `USE_CURRENT_INFERENCE` to `Literal[False] = False`.
2. Run pyright on this file.

When it's ready, move passing desired assertions into `type_inference.py`.
"""

from typing import Any, Callable, Literal, assert_type, cast

from signified import (
    Binding,
    Computed,
    Effect,
    HasValue,
    ReactiveValue,
    Signal,
    as_rx,
    computed,
    deep_unref,
    effect,
    is_reactive,
    unref,
)

# NOTE: Keep annotation/value in sync so pyright can treat this as a constant.
USE_CURRENT_INFERENCE: Literal[True] = True


def test_todo_getattr_data_attributes():
    # Why this fails:
    # __getattr__ is intentionally typed as Computed[Any] for arbitrary
    # attribute names, because static typing can't resolve proxy attributes.
    class Person:
        def __init__(self, name: str, age: int) -> None:
            self.name = name
            self.age = age

    person = Signal(Person("Alice", 30))

    if USE_CURRENT_INFERENCE:
        assert_type(person.name, Computed[Any])
        assert_type(person.age, Computed[Any])
    else:
        assert_type(person.name, Computed[str])
        assert_type(person.age, Computed[int])


def test_todo_getattr_nested_object_attribute():
    # Why this fails:
    # Same proxy limitation as above. Without proxy-aware typing support
    # (or richer intersection/protocol modeling), nested attribute access
    # through __getattr__ remains Computed[Any].
    class Person:
        def __init__(self, name: str) -> None:
            self.name = name

    class Wrapper:
        def __init__(self, person: Person) -> None:
            self.person = person

    wrapped = Signal(Wrapper(Person("Alice")))

    if USE_CURRENT_INFERENCE:
        assert_type(wrapped.person, Computed[Any])
    else:
        assert_type(wrapped.person, Computed[Person])


def test_todo_is_reactive_negative_narrowing[T](value: HasValue[T]):
    # Why this fails:
    # TypeGuard narrows only its positive branch. TypeIs does not make the
    # generic claim sound: T itself may be a reactive type, so excluding every
    # reactive wrapper from HasValue[T] cannot always leave T. Callers with a
    # concrete non-reactive T can narrow by another guard if needed.
    if is_reactive(value):
        return
    if USE_CURRENT_INFERENCE:
        assert_type(value, HasValue[T])
    else:
        assert_type(value, T)


def test_todo_higher_order_has_value(value: HasValue[Signal[int]]):
    # Why this fails:
    # HasValue[T] assumes that both its plain-T and ReactiveValue[T] branches
    # resolve to T. That is false when T itself is reactive: a direct
    # Signal[int] unwraps to int, while Signal[Signal[int]] unwraps to
    # Signal[int]. Python cannot express "T, unless T is reactive".
    if USE_CURRENT_INFERENCE:
        assert_type(unref(value), Signal[int])
        assert_type(as_rx(value), ReactiveValue[Signal[int]])
        if is_reactive(value):
            assert_type(value, ReactiveValue[Signal[int]])
    else:
        assert_type(unref(value), int | Signal[int])
        assert_type(as_rx(value), Signal[int] | ReactiveValue[Signal[int]])
        if is_reactive(value):
            assert_type(value, Signal[int] | ReactiveValue[Signal[int]])


def test_todo_as_rx_optional_precision(value: HasValue[int] | None):
    # Why this fails:
    # The distributed-union overload accepts the input, but Pyright groups None
    # with int and widens part of the result to ReactiveValue[int | None]. At
    # runtime the None branch specifically creates Signal[None].
    result = as_rx(value)
    if USE_CURRENT_INFERENCE:
        assert_type(result, ReactiveValue[int] | ReactiveValue[int | None])
    else:
        assert_type(result, ReactiveValue[int] | Signal[None])


def test_todo_computed_and_effect_preserve_parameter_types():
    # Why this fails:
    # The decorators must map every original parameter T to HasValue[T]. Python
    # has ParamSpec, but no mapped-ParamSpec operation, so the wrappers currently
    # expose (...) and accept arguments of any type.
    @computed
    def stringify(value: int) -> str:
        return str(value)

    @effect
    def consume(value: int) -> None:
        pass

    if USE_CURRENT_INFERENCE:
        assert_type(stringify, Callable[..., Computed[str]])
        assert_type(consume, Callable[..., Effect])
    else:
        assert_type(stringify, Callable[[HasValue[int]], Computed[str]])
        assert_type(consume, Callable[[HasValue[int]], Effect])


def test_todo_reactive_callable_accepts_reactive_arguments(
    function: Signal[Callable[[int], str]], argument: Signal[int]
):
    # Why this fails:
    # __call__ preserves the wrapped callable's ParamSpec, which requires int,
    # but its runtime implementation shallowly unwraps a direct Signal[int]. As
    # with the decorators, Python cannot map every parameter to HasValue[T].
    if USE_CURRENT_INFERENCE:
        result = function(unref(argument))
    else:
        result = function(argument)
    assert_type(result, Computed[str])


def test_todo_covariant_read_only_reactive_source(value: Signal[int]):
    # Why this fails:
    # Signal must remain invariant because .value is writable. A separate
    # covariant read-only ReactiveSource protocol could allow Signal[int] where
    # a consumer only needs a source of int | str.
    if USE_CURRENT_INFERENCE:
        assert_type(value, Signal[int])
    else:
        assert_type(value, ReactiveValue[int | str])


def test_todo_binding_accepts_distributed_union_sources(
    value: HasValue[int] | HasValue[str], binding: Binding[int | str]
):
    # Why this fails:
    # Binding only reads a selected reactive source, but ReactiveValue is a
    # union of invariant classes. A narrow Signal[int] therefore cannot be used
    # as a source for Binding[int | str] without a cast.
    if USE_CURRENT_INFERENCE:
        widened = cast(HasValue[int | str], value)
        created = Binding(widened)
        binding.set(widened)
        assert_type(created, Binding[int | str])
    else:
        created = Binding(value)
        binding.set(value)
        assert_type(created, Binding[int | str])


def test_todo_deep_unref_result_type():
    # Why this fails:
    # deep_unref recursively transforms reactive boundaries and containers.
    # Python has no recursive conditional type that can describe its general
    # output, so even a statically known chain of Signals returns Any.
    result = deep_unref(Signal(Signal(Signal(1.0))))
    if USE_CURRENT_INFERENCE:
        assert_type(result, Any)
    else:
        assert_type(result, float)


def test_todo_pow_negative_exponent():
    # Why this fails:
    # `__pow__` infers the promoted operand type, but the real result depends on
    # the exponent's *value*, not its type: 2 ** -1 is 0.5 and True ** -1 is 1.0.
    # Typeshed covers the literal case with _NegativeInteger overloads and falls
    # back to Any for an int of unknown sign. signified keeps the promoted type
    # instead, because Any would erase the result of every well-behaved `**`.
    if USE_CURRENT_INFERENCE:
        assert_type(Signal(2) ** -1, Computed[int])
        assert_type(Signal(True) ** -1, Computed[int])
    else:
        assert_type(Signal(2) ** -1, Computed[float])
        assert_type(Signal(True) ** -1, Computed[float])


def test_todo_pow_fractional_exponent_of_negative_base():
    # Why this fails:
    # A fractional exponent over a negative base produces a complex number
    # ((-8) ** 0.5), but the sign of the base is a value, not a type. Even a
    # literal -8 cannot help: Signal widens int literals to int on construction,
    # so no overload can distinguish a negative base from a positive one.
    if USE_CURRENT_INFERENCE:
        assert_type(Signal(-8) ** 0.5, Computed[float])
    else:
        assert_type(Signal(-8) ** 0.5, Computed[complex])
