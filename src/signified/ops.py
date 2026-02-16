from collections.abc import Callable
from typing import Any, get_origin, get_args
import builtins


from signified.core import computed, Signal

# Computed wrappers (signature is consumed this way, so maybe change?)
sum = computed(builtins.sum)
min = computed(builtins.min)
max = computed(builtins.max)
all = computed(builtins.all)
any = computed(builtins.any)
pow = computed(builtins.pow)

# Special types (operate as if they are callables, cannot subclass)
range = computed(builtins.range)
memoryview = computed(builtins.memoryview)
slice = computed(builtins.slice)
bool = computed(builtins.bool)


def trigger_notify(signal: Signal, func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any):
        res = func(*args, **kwargs)
        signal.notify()
        return res
    return wrapper


# Type Hint magic to intercept the origin type of a wrapped builtin
class _SignalWrapper[T](Signal[T]):
    __wrapped_builtins__: dict[str, type] = {}
      
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        
        # Extract base from hint
        base_type, *_ = get_args(self.__orig_bases__[0])
        if origin := get_origin(base_type):
            base_type = origin
        
        # Cache type wrapper or get cached wrapper
        _wrapped_name = f'signified_{base_type.__name__}'
        if _wrapped_name in self.__wrapped_builtins__:
            base_type = self.__wrapped_builtins__[_wrapped_name]
        else:
            base_type = type(_wrapped_name, (base_type, ), {})
            self.__wrapped_builtins__[_wrapped_name] = base_type
        
        # Create the signal
        super().__init__(base_type(*args, **kwargs))
        
        # Apply instance wrapper on base type
        for f in getattr(self, '__mutators__', []):
            _trigger = trigger_notify(self, getattr(self.value, f))
            setattr(self.value, f, _trigger)

# Mutable Types
class list[T](_SignalWrapper[builtins.list[T]]):
    __mutators__ = ('append', 'pop', 'extend', 'clear', 'insert', 'remove', 'reverse', 'sort')
    
class dict[K, V](_SignalWrapper[builtins.dict[K, V]]):
    __mutators__ = ('clear', '__setitem__', 'update', 'pop', 'setdefault')

class set[T](_SignalWrapper[builtins.set[T]]):
    __mutators__ = (
        'add', 'pop', 'clear', 'discard', 'remove', 'update',
        'intersection_update', '__iand__',
        'difference_update', '__isub__',
        'symmetric_difference_update', '__ixor__',
    )

# Immutable Types (NOTE: These become mutable when wrapped by Signal)
class tuple[T](_SignalWrapper[builtins.tuple[T]]): ...
class int(_SignalWrapper[builtins.int]): ...
class str(_SignalWrapper[builtins.str]): ...
class frozenset(_SignalWrapper[builtins.frozenset]): ...


if __name__ == '__main__':
    print(
        """Setup:

x: list[int] = list(range(5))
y = Signal(x[0] >= 3).where(max(x), min(x))
z = sum(x)
j = z**y
k = range(y)

"""
)
    x: list[int] = list(range(5))
    y = Signal(x[0] >= 3).where(max(x), min(x))
    z = sum(x)
    j = z**y
    k = range(y)
    print('Initial Values')
    print(f'{x=}, {y=}, {z=}, {j=}, {k=}')
    
    print('\nsort x')
    x.value.sort(reverse=True) # type: ignore
    print(f'{x=}, {y=}, {z=}, {j=}, {k=}')