"""Three ways to create an effect.

Run with: uv run examples/effects/basics.py
"""

from signified import Effect, Signal, effect


@effect
def log_count(value: int, label: str) -> None:
    # A Signal argument arrives as its current value on each run. Other
    # arguments, like label, pass through unchanged.
    print(f"{label}: {value}")


def example() -> None:
    count = Signal(0)

    print("1: Create an Effect object directly:")
    observer = Effect(lambda: print(f"Effect: {count.value}"))
    try:
        count.value = 1
        count.value = 1  # Unchanged scalar values do not trigger another run.
    finally:
        observer.dispose()

    print("\n2: Use the @effect decorator:")
    logger = log_count(count, "@effect")
    try:
        count.value = 2
    finally:
        logger.dispose()

    print("\n3: Use .rx.effect():")
    display = count.rx.effect(lambda value: print(f"rx.effect: {value}"))
    try:
        count.value = 3
    finally:
        display.dispose()


if __name__ == "__main__":
    example()
