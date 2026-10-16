from signified import Effect, Signal, batch

price = Signal(10)
quantity = Signal(2)
watcher = Effect(lambda: print("total:", price.value * quantity.value))

print("Without batch:")
price.value = 12
quantity.value = 3

print("With batch:")
with batch():
    price.value = 15
    quantity.value = 4
# The effect runs once, after the block.

watcher.dispose()
