import time
from datetime import datetime

from signified import Signal, effect


def example() -> None:
    """
    Demonstrates using an effect to log state changes with timestamps.
    """
    counter = Signal(0)
    log_entries = []

    def log_changes(count):
        timestamp = datetime.now().strftime("%H:%M:%S")
        new_entry = f"{timestamp}: Counter changed to {count}"
        print(f"📝 {new_entry}")
        log_entries.append(new_entry)

    # Store the effect in a variable to keep it alive
    print("Creating the logging effect")
    effect(log_changes)(counter)

    print("Incrementing counter several times...")
    for i in range(1, 4):
        time.sleep(0.5)
        counter.value = i

    print("\nFinal log entries:")
    for entry in log_entries:
        print(f"  {entry}")


if __name__ == "__main__":
    example()
