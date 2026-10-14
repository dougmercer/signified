from signified import Signal, computed

@computed
def welcome(name):
    return f"Welcome back, {name}!"

username = Signal(None)
message = username.rx.is_not(None).rx.where(welcome(username), "Please log in")
print(message.value)

username.value = "admin"
print(message.value)
