"""Batch updates and follow only the selected sensor's readings.

`Sensors` is an ordinary dataclass. `@tracked_fields` makes its attributes
reactive: a calculation or effect that reads `sensors.primary` runs again when
`sensors.primary` is reassigned. Writes are plain attribute assignments.

- `select_sensors` is a calculation that reads whichever sensor is in use. It
  takes the whole `sensors` object and reads its fields inside, so it follows
  them. Passing `sensors.primary` instead would pass today's number, which
  never changes.
- `render` is an effect that prints the selected reading with its label. It
  runs again whenever either one changes.
- `batch()` groups several writes into one update.

Expected output:

    Temperature: 20 C

    Batch writes into one display update:
    Temperature: 22 C

    Rename the display:
    Office: 22 C

    Switch to the backup sensor:
    Office: 16 C
    The primary sensor is no longer a dependency:
    Office: 19 C

Run with: uv run examples/effects/dashboard.py
"""

from dataclasses import dataclass

from signified import Effect, batch, computed, tracked_fields


@tracked_fields
@dataclass(slots=True)
class Sensors:
    primary: int = 20
    backup: int = 18
    use_backup: bool = False
    label: str = "Temperature"


@computed
def select_sensors(sensors: Sensors) -> int:
    return sensors.backup if sensors.use_backup else sensors.primary


def example() -> None:
    sensors = Sensors()
    selected = select_sensors(sensors)

    def render() -> None:
        print(f"{sensors.label}: {selected.value} C")

    # Note: we hold a reference to effect so that it doesn't get
    # immediately garbage collected.
    display = Effect(render)  # Temperature: 20 C  # noqa

    print("\nBatch writes into one display update:")
    with batch():
        sensors.primary = 22
        sensors.backup = 16

    print("\nRename the display:")
    sensors.label = "Office"  # Office: 22 C

    print("\nSwitch to the backup sensor:")
    sensors.use_backup = True  # Office: 16 C
    print("The primary sensor is no longer a dependency:")
    sensors.primary = 99  # No display update.
    sensors.backup = 19  # Office: 19 C


if __name__ == "__main__":
    example()
