"""Rebuild an index of Markdown notes whenever the notes folder changes.

`helper.py` creates a temporary notes folder and plays the part of you editing
it. This file only watches the folder and reacts:

- `notes` is a signal holding each note's text. Whenever anything in the
  folder changes, the watcher re-reads the folder into `notes`.
- `table_of_contents` is a calculation that lists each note's title.
- `write_index` is an effect that writes the table of contents to `index.md`.
  It is the only code that changes anything outside the program.

Editing a note's body without changing its title produces the same table of
contents, so `write_index` does not run and `index.md` is left alone.

The watcher runs on its own thread, so `notes` changes and `write_index` runs
there. That is fine because nothing else uses these values while the edits
happen: Signified needs each set of connected values used by one thread at a
time. If other code also used `notes` while watching, you would pass the
watcher's events to that code's thread, for example through a queue.

Expected output:

    Wrote index.md:
    - Groceries (groceries.md)
    - Ideas (ideas.md)

    Adding travel.md
    Wrote index.md:
    - Groceries (groceries.md)
    - Ideas (ideas.md)
    - Travel plans (travel.md)

    Adding eggs to groceries.md

    Renaming Ideas to Project ideas
    Wrote index.md:
    - Groceries (groceries.md)
    - Project ideas (ideas.md)
    - Travel plans (travel.md)

Run with: uv run --with watchdog examples/effects/notes_index/example.py
"""

from pathlib import Path

from helper import edit_notes, notes_folder
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from signified import Signal, computed, effect


def read_notes(folder: Path) -> dict[str, str]:
    return {path.name: path.read_text() for path in sorted(folder.glob("*.md"))}


@computed
def table_of_contents(notes: dict[str, str]) -> str:
    titles = {name: text.splitlines()[0].removeprefix("# ") for name, text in notes.items()}
    return "\n".join(f"- {title} ({name})" for name, title in titles.items())


@effect
def write_index(toc: str, path: Path) -> None:
    path.write_text(toc + "\n")
    print(f"Wrote {path.name}:\n{toc}")


class UpdateNotes(FileSystemEventHandler):
    """Re-read the folder into `notes` whenever anything in it changes."""

    def __init__(self, folder: Path, notes: Signal[dict[str, str]]) -> None:
        self.folder = folder
        self.notes = notes

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.notes.value = read_notes(self.folder)


def example() -> None:
    with notes_folder() as folder:
        notes = Signal(read_notes(folder))
        writer = write_index(table_of_contents(notes), folder.parent / "index.md")

        # Polling works on every OS; native macOS notifications can go missing.
        observer = PollingObserver(timeout=0.1)
        observer.schedule(UpdateNotes(folder, notes), str(folder))
        observer.start()
        try:
            edit_notes(folder)
        finally:
            observer.stop()
            observer.join()
            writer.dispose()


if __name__ == "__main__":
    example()
