---
hide:
  - navigation
---
# Writing Plugins

Signified provides a plugin system built on top of [pluggy](https://pluggy.readthedocs.io/).

## Important: Hooks Are Disabled by Default

By default, `signified.plugins.pm` is a no-op manager. To activate real hooks:

1. Install plugin support:

    ```bash
    pip install "signified[plugins]"
    ```

2. Run with:

    ```bash
    SIGNIFIED_ENABLE_HOOKS=1
    ```

Without this environment variable set, plugin hooks will not execute.

## Plugin Hooks

The plugin system provides hooks for key events in a reactive value's lifecycle:

- `read`: Called whenever a reactive value's current value is accessed
- `created`: Called when a new reactive value is instantiated
- `updated`: Called when a reactive value's content changes
- `named`: Called when a reactive value is given a name

These hooks allow plugins to observe and respond to the complete lifecycle of reactive values.

## Creating a Plugin

Implement hooks with `@hookimpl`, then register with `pm`:

```python
from typing import Any

from signified import Signal, Variable
from signified.plugins import hookimpl, pm

class MyPlugin:
    def __init__(self) -> None:
        self.created_count = 0

    @hookimpl
    def created(self, value: Variable[Any]) -> None:
        self.created_count += 1
        print(f"created: {value:d}")  # :d = debug format: shows type and id

plugin = MyPlugin()
pm.register(plugin)

x = Signal(1)
y = x + 1
print(plugin.created_count)  # 2 when hooks are enabled

pm.unregister(plugin)
```

## Plugin Management

The global manager lives at `signified.plugins.pm`:

```python
from signified.plugins import pm

pm.register(my_plugin)
pm.unregister(my_plugin)
```

## Logging Example

```python
from __future__ import annotations

import logging
from typing import Any

from signified import Signal, Variable
from signified.plugins import hookimpl, pm


class ReactiveLogger:
    def __init__(self, logger: Any | None = None):
        if logger is None:
            _logger = logging.getLogger(__name__)
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)
            _logger.addHandler(handler)
            _logger.setLevel(logging.INFO)
        else:
            _logger = logger
        self.logger = _logger

    @hookimpl
    def created(self, value: Variable[Any]) -> None:
        self.logger.info(f"Created {value:d}")

    @hookimpl
    def updated(self, value: Variable[Any]) -> None:
        self.logger.info(f"Updated {value:n} to {value.value}")

    @hookimpl
    def named(self, value: Variable[Any]) -> None:
        self.logger.info(f"Named {type(value).__name__}(id={id(value)}) as {value:n}")

logger_plugin = ReactiveLogger()
pm.register(logger_plugin)

x = Signal(1).add_name("x")
y = (x + 1).add_name("y")
x.value = 5
print(y.value)  # 6

pm.unregister(logger_plugin)
```
