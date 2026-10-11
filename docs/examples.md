# Examples

Complete programs that use Signified. Each one runs on its own; the command to
run it from a clone of the repository is at the top of the file.

## Effects

### Three ways to create an effect {#effect-basics}

Create an `Effect` object, decorate a function with `@effect`, or call
`.rx.effect()` on a reactive value.

```python title="examples/effects/basics.py"
--8<-- "examples/effects/basics.py"
```

### Save settings when they change {#autosave}

An effect writes settings to a file, and `batch()` combines related edits into
one save.

```python title="examples/effects/autosave.py"
--8<-- "examples/effects/autosave.py"
```

### Follow the selected sensor {#dashboard}

`@tracked_fields` makes a dataclass's attributes reactive, so a display follows
whichever sensor is selected.

```python title="examples/effects/dashboard.py"
--8<-- "examples/effects/dashboard.py"
```

### Rebuild an index when files change {#notes-index}

A file watcher updates a signal, and an effect rewrites `index.md` only when
the notes' titles change. This one needs `watchdog`.

=== "example.py"

    ```python title="examples/effects/notes_index/example.py"
    --8<-- "examples/effects/notes_index/example.py"
    ```

=== "helper.py"

    ```python title="examples/effects/notes_index/helper.py"
    --8<-- "examples/effects/notes_index/helper.py"
    ```

## Plugins

### Count reads and writes {#access-tracker}

A plugin that records how often each reactive value is read and changed.

```python title="examples/plugins/access_tracker.py"
--8<-- "examples/plugins/access_tracker.py"
```
