# Writing plugins

Plugins let you log or inspect reads and changes to reactive values.
Signified uses [pluggy](https://pluggy.readthedocs.io/) to call your plugin's
methods when these events happen.

## Enable plugins

Install the optional dependency:

```bash
pip install "signified[plugins]"
```

Set `SIGNIFIED_ENABLE_HOOKS=1` before importing Signified. For example, run a
script with:

```bash
SIGNIFIED_ENABLE_HOOKS=1 python your_script.py
```

Without this setting, registering a plugin has no effect.

## Available hooks {#plugin-hooks}

Each hook receives the reactive object as its `value` argument:

| Hook | When it runs |
| --- | --- |
| `created` | A reactive value is created. |
| `read` | Its current value is read. |
| `updated` | It sends a change notification. |
| `named` | It is given a name. |

## Create and register a plugin {#creating-a-plugin}

Implement the hooks you need with `@hookimpl`, then register the instance.
This plugin counts new reactive values:

```python
from typing import Any

from signified import Signal, Variable
from signified.plugins import hookimpl, plugin_manager

class CreationCounter:
    def __init__(self) -> None:
        self.count = 0

    @hookimpl
    def created(self, value: Variable[Any]) -> None:
        self.count += 1
        print(f"Created {value:d}")  # :d shows the object's type and ID.

plugin = CreationCounter()
plugin_manager.register(plugin)

x = Signal(1)
y = x + 1
print(plugin.count)  # 2 when hooks are enabled

plugin_manager.unregister(plugin)
```

Use `logging` in place of `print` if your application already has logging set
up. Unregister the plugin when you no longer need it. The older `pm` name is
an alias for `plugin_manager`.
