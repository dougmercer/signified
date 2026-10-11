"""Stand in for a person editing notes, so the example runs unattended.

Nothing here uses Signified.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


@contextmanager
def notes_folder() -> Generator[Path]:
    """Create a temporary folder with two notes. It is deleted on exit."""
    with TemporaryDirectory() as temporary:
        folder = Path(temporary, "notes")
        folder.mkdir()
        (folder / "groceries.md").write_text("# Groceries\n- milk\n")
        (folder / "ideas.md").write_text("# Ideas\n- a reactive to-do app\n")
        yield folder


def edit_notes(folder: Path) -> None:
    """Add a note, change one's body, and retitle another.

    Pauses half a second before each edit and after the last, so a watcher has
    time to notice each one.
    """
    edits = [
        ("Adding travel.md", "travel.md", "# Travel plans\n- book flights\n"),
        ("Adding eggs to groceries.md", "groceries.md", "# Groceries\n- milk\n- eggs\n"),
        ("Renaming Ideas to Project ideas", "ideas.md", "# Project ideas\n- a reactive to-do app\n"),
    ]
    for message, name, text in edits:
        time.sleep(0.5)
        print(f"\n{message}")
        (folder / name).write_text(text)
    time.sleep(0.5)
