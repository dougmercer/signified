# Writing Plugins

Signified provides a plugin system built on top of [pluggy](https://pluggy.readthedocs.io/) that allows you to extend and customize its behavior. This guide explains the basics of creating plugins for signified.

## Plugin Hooks

The plugin system provides hooks for key events in a reactive value's lifecycle:

- `read`: Called whenever a reactive value's current value is accessed
- `created`: Called when a new reactive value is instantiated
- `updated`: Called when a reactive value's content changes
- `named`: Called when a reactive value is given a name

These hooks allow plugins to observe and respond to the complete lifecycle of reactive values.

Additional hooks may be added in the future. If you have a good idea for a plugin that would benefit from additional hooks, please let me know!

## Creating a Plugin

To create a plugin:

1. Create a class that will contain your hook implementations
2. Implement any desired hooks using the `@hookimpl` decorator (available from `signified.plugins`)
3. Register your plugin with the global plugin manager `pm` (also available in `signified.plugins`)

Here's a minimal example:

```python
from signified.plugins import hookimpl, pm
from signified import ReactiveValue
from typing import Any

class MyPlugin:
    @hookimpl
    def created(self, value: ReactiveValue[Any]) -> None:
        # Do something when a reactive value is created
        pass

# Register the plugin
plugin = MyPlugin()
pm.register(plugin)
```

## Plugin Management

The library maintains a global plugin manager instance in `signified.plugins.pm`. Plugins can be registered and unregistered at runtime:

```python
from signified.plugins import pm

# Register a plugin
pm.register(my_plugin)

# Remove a plugin
pm.unregister(my_plugin)
```

## More complex example

I created a [simple logging plugin](https://github.com/dougmercer/signified_logging).

```python
from __future__ import annotations

import logging
from typing import Any

from signified import Variable
from signified.plugins import hookimpl, pm


class ReactiveLogger:
    """A logger plugin for tracking reactive value lifecycle."""

    def __init__(self, logger: Any | None = None):
        """Initialize with optional logger, defaulting to standard logging."""
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
    def created(self, value: Variable[Any, Any]) -> None:
        """Log when a reactive value is created.

        Args:
            value: The created reactive value
        """
        self.logger.info(f"Created {value:d}")

    @hookimpl
    def updated(self, value: Variable[Any, Any]) -> None:
        """Log when a reactive value is updated.

        Args:
            value: The updated reactive value
        """
        self.logger.info(f"Updated {value:n} to {value.value}")

    @hookimpl
    def named(self, value: Variable[Any, Any]) -> None:
        """Log when a reactive value is named.

        Args:
            value: The reactive value that was assigned a name.
        """
        self.logger.info(f"Named {type(value).__name__}(id={id(value)}) as {value:n}")

DEFAULT_LOGGING_PLUGIN = ReactiveLogger()
pm.register(DEFAULT_LOGGING_PLUGIN)
```

Here, we implement logging behavior for the `created`, `updated`, and `named` hooks.

Finally, at the end, we create the plugin and register it to the plugin manager.
