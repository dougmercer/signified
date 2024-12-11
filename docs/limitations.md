# Known Limitations

## Type Inference

This library's type hints do not work with `mypy`, but they do work relatively well with `pyright`.

## Methods on Mutable Collection

When working with collections like `list`s, methods that mutate the underlying object don't trigger `signified` to notify observers:

```python
from signified import Signal

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
```
