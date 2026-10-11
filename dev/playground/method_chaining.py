from signified import Signal

text = Signal("  Hello, World!  ")
processed = text.strip().lower().replace(",", "")

print(processed.value)
text.value = "  Goodbye, World!  "
print(processed.value)
