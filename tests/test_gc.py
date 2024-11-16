import gc

from signified import Signal, computed


def test_gc_single_observer():
    x = Signal(1)
    y = computed(lambda x: x + 1)(x)
    assert len(x._observers) == 1

    y = None  # noqa: F841
    gc.collect()
    assert len(x._observers) == 0


def test_gc_multiple_observers():
    x = Signal(1)
    observers = [computed(lambda x: x + i)(x) for i in range(3)]
    assert len(x._observers) == 3

    observers.pop()
    gc.collect()
    assert len(x._observers) == 2

    observers.clear()
    gc.collect()
    assert len(x._observers) == 0

def test_custom_observer_protocol():
   class Counter:
       def __init__(self):
           self.updates = 0
           
       def update(self):
           self.updates += 1
   
   x = Signal(1)
   counter = Counter()
   x.subscribe(counter)
   assert len(x._observers) == 1
   
   x.value = 2
   assert counter.updates == 1
   
   x.value = 3 
   assert counter.updates == 2

def test_unhashable_observer():
   class ListObserver:
       def __init__(self):
           self.history = []  # Lists aren't hashable
           
       def update(self):
           self.history.append("updated")
           
   x = Signal(1)
   observer = ListObserver()
   
   # Should raise TypeError due to unhashable list attribute
   x.subscribe(observer)

def test_unhashable_observer():
    class DictObserver(dict):
        def update(self):
            self['updates'] = self.get('updates', 0) + 1
    
    x = Signal(1)
    observer = DictObserver()
    x.subscribe(observer)  # Should fail since dicts are unhashable
