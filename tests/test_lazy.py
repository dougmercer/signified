from signified import Computed, Signal, computed

def test_lazy_access():
    a = Signal(1000)
    b = Signal(1)
    c = a ** b
    assert c.value == 1000
    
    # If this immediately propogates, the test will crash
    b.value = 1000000
    assert c._value == 1000
    
    # Make sure the version for c is incremented 
    assert c.store.version[c] == 1
    a.value = 1
    assert c.store.version[c] == 2
    
    # The computation is now easy
    b.value = 1
    # Evaluate c
    assert c.value == 1
    
def test_lazy_versioning():
    a = Signal('a')
    store = a.store
    
    b = a + 'b'
    c = b + 'c'
    d = c + 'd'
    z = a + b + c + d
    
    assert z.value == 'aababcabcd'
    a.value = 'A'
    
    assert z._value == 'aababcabcd'
    
    assert store.version[b] == 1
    assert store.version[c] == 1
    assert store.version[d] == 1
    assert store.version[z] == 1
    
    assert z.value == 'aababcabcd'.replace('a', 'A')
    assert b.value == 'ab'.replace('a', 'A')
    
    assert store.version[b] == 0
    assert store.version[c] == 0
    assert store.version[d] == 0
    assert store.version[z] == 0