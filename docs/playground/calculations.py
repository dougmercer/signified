from signified import Signal

price = Signal(10)
quantity = Signal(2)
total = price * quantity

print("total:", total.value)
quantity.value = 3
print("total:", total.value)
