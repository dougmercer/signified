"""Save application settings when they change, combining related edits.

Run with: uv run examples/effects/autosave.py
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from signified import Signal, batch, effect


@effect
def save_settings(settings_path: Path, current_theme: str, current_font_size: int) -> None:
    settings = {"theme": current_theme, "font_size": current_font_size}
    # write_text opens and closes the file on each run.
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {settings}")


def example() -> None:
    theme = Signal("light")
    font_size = Signal(14)

    with TemporaryDirectory(prefix="signified-settings-") as temporary:
        settings_path = Path(temporary) / "settings.json"
        saver = save_settings(settings_path, theme, font_size)  # Saves the initial settings.
        try:
            # Both writes produce a single save with the final settings.
            with batch():
                theme.value = "dark"
                font_size.value = 18

            font_size.value = 20  # Saves synchronously before this line returns.
        finally:
            saver.dispose()

        theme.value = "light"  # No save after disposal.
        print("\nLast saved settings:")
        print(settings_path.read_text(encoding="utf-8"), end="")
        # The temporary directory is removed when this example exits.


if __name__ == "__main__":
    example()
