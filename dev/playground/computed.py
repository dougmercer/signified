from signified import Signal, computed

@computed
def stats(numbers):
    return {"sum": sum(numbers), "mean": sum(numbers) / len(numbers)}

numbers = Signal([1, 2, 3, 4])
summary = stats(numbers)
print(summary.value)

numbers.value = [10, 20, 30]
print(summary.value)
