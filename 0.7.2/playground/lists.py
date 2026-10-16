from signified import Signal, computed

numbers = Signal([1, 2, 3])
total = computed(sum)(numbers)
print("total:", total.value)

numbers[0] = 10  # item assignment sends an update
print("total:", total.value)

numbers.value.append(4)  # changing the raw list does not
print("total:", total.value)
numbers.update()  # so tell Signified about it
print("total:", total.value)
