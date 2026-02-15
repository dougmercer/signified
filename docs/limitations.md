# Known Limitations

## Type Inference

This library's type hints do not work with `mypy`, but they do work well with `pyright`.

## In-Place Mutation of Mutable Collections

When working with values like `list` and `dict`, mutating via methods on the underlying object does not automatically notify observers.

```python
from signified import Signal, computed

# This won't work as expected
numbers = Signal([1, 2, 3])
sum_numbers = computed(sum)(numbers)
print(sum_numbers.value)  # 6

numbers.value.append(4)   # Mutation doesn't trigger update
print(sum_numbers.value)  # Still 6, not 10 as expected

# Instead, do one of these:
# 1. Assign a new list
numbers.value = [1, 2, 3, 4]
print(sum_numbers.value)  # 10

# 2. Create a new list with the existing values
numbers.value = numbers.value + [4]
print(sum_numbers.value) # 10

# 3. For lists/dicts, use __setitem__ on the signal
numbers[0] = 99
print(sum_numbers.value)  # 108
```

## Plugin Hooks Are Opt-In

Plugin hooks are disabled by default. To enable hook execution, install the plugin extra and set:

```bash
SIGNIFIED_ENABLE_HOOKS=1
```
