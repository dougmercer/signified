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


# dead simple wrapper to run around mutator methods that send a notification after
# mutation
def notify_after(func: Callable[..., Any], sig: Signal[Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any):
        res = func(*args, **kwargs)
        sig.notify()
        return res
    return wrapper


# Type Hint magic to intercept the origin type of a wrapped builtin
class _SignalWrapper[T](Signal[T]):    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        base_type, *_ = get_args(self.__orig_bases__[0])
        if origin := get_origin(base_type):
            base_type = origin
        # This currently constructs a new type on every init, but it does work
        # definitely find a better way
        base_type = type(f'signaled_{base_type.__name__}', (base_type, ), {})
        super().__init__(base_type(*args, **kwargs))
        
        if _mutators := getattr(self, '__mutators__', None):
            for mutator in _mutators:
                func: Callable[..., Any] = getattr(self.value, mutator)
                setattr(self.value, mutator, notify_after(func, self))


# Mutable Types
class list[T](_SignalWrapper[builtins.list[T]]):
    __mutators__ = ('append', 'pop', 'extend', 'clear', 'insert', 'remove', 'reverse', 'sort')
    
class dict[K, V](_SignalWrapper[builtins.dict[K, V]]):
    __mutators__ = ('clear', '__setitem__', 'update', 'pop', 'setdefault')

class set[T](_SignalWrapper[builtins.set[T]]):
    __mutators__ = (
        'add', 'pop', 'clear', 'discard', 'remove', 'update'
        'intersection_update', '__iand__',
        'difference_update', '__isub__',
        'symmetric_difference_update', '__ixor__',
    )

# Immutable Types (NOTE: These become mutable when wrapped by Signal)
class tuple[T](_SignalWrapper[builtins.tuple[T]]): ...
class int(_SignalWrapper[builtins.int]): ...
class str(_SignalWrapper[builtins.str]): ...
class frozenset(_SignalWrapper[builtins.frozenset]): ...

