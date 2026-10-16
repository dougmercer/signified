from signified import Signal, effect

@effect
def show(total):
    print(f"Total: ${total:.2f}")

price = Signal(10)
quantity = Signal(2)
watcher = show(price * quantity)  # runs right away

quantity.value = 3
price.value = 12.5

watcher.dispose()
price.value = 99  # no output after dispose
