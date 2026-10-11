from signified import Binding, Signal

frame = Signal(0)
x = Binding(0)    # a plain number for now
label_x = x + 10  # a label that sits to the right of the shape

x.value = 5
print("label_x:", label_x.value)

x.value = frame * 2  # now follow an animation
for f in [10, 20, 30]:
    frame.value = f
    print("label_x:", label_x.value)
