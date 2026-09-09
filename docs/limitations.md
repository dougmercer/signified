---
hide:
  - navigation
---
# Known Limitations

## Type Inference

This library's type hints do not work with `mypy`, but they do work well with `pyright`.

## In-place mutation

Raw mutable objects do not become reactive containers. Replace their value or
explicitly notify after mutation:

```python
from signified import Signal, computed

numbers = Signal([1, 2, 3])
total = computed(sum)(numbers)
assert total.value == 6
numbers.value.append(4)
assert total.value == 6  # cached: raw mutation did not notify
numbers.update()
assert total.value == 10
numbers.value = numbers.value + [5]
assert total.value == 15
numbers[0] = 99  # wrapper assignment also notifies
assert total.value == 113
```

## Scheduling and snapshots

Reactive operations must run on one thread. `batch()` and `untracked()` are
synchronous scopes and must not span `await`. Batching defers effects but does
not isolate reads or roll back applied changes. Cascading writes may run an
effect more than once per flush.

`deep_unref` only enters registered exact types. Unknown objects remain shared
and may hide reactive values; the result is neither a detached snapshot nor
guaranteed serializable. All encountered cycles raise. Reactive containers,
transactional updates, and detached snapshots are deferred.

## Plugin Hooks Are Opt-In

Plugin hooks are disabled by default to keep the base install dependency-free and low-overhead. To activate them, install the plugin extra and set the environment variable:

```bash
pip install "signified[plugins]"
SIGNIFIED_ENABLE_HOOKS=1
```

See the [Plugins guide](plugins.md) for full details on writing and registering plugins.
