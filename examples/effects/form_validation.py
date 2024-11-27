import time

from signified import Signal, effect


def example() -> None:
    """
    Validating form consisting of multiple fields.

    There are *absolutely* better ways of doing this.

    But... it kind of works!
    """

    username = Signal("")
    email = Signal("")
    is_valid = Signal(False)
    error_message = Signal("")

    def validate_form(name, mail):
        print("\n🔍 Validating form data:")
        print(f"  Username: '{name}'")
        print(f"  Email: '{mail}'")

        if len(name) < 3:
            is_valid.value = False
            error_message.value = "❌ Username must be at least 3 characters"
        elif "@" not in mail:
            is_valid.value = False
            error_message.value = "❌ Invalid email address"
        else:
            is_valid.value = True
            error_message.value = "✅ Form is valid!"

        print(f"Validation result: {error_message.value}")
        print(f"Form valid: {is_valid.value}")

    effect(validate_form)(username, email)

    # Test cases
    test_cases = [
        ("al", "test@example.com"),
        ("alice", "invalid-email"),
        ("alice", "alice@example.com"),
    ]

    for name, mail in test_cases:
        print("\n\n\n\n")
        print("=" * 50)
        print("Testing with new input...")
        print("=" * 50)
        username.value, email.value = name, mail
        time.sleep(1)
        print("=" * 50)


if __name__ == "__main__":
    example()
