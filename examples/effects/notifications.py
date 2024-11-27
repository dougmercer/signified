import time

from signified import Signal, effect


def example():
    """
    Shows how to combine monitoring and notifications using effects.
    """

    temperatures = Signal([20, 22, 21, 23])
    threshold = Signal(22)
    notifications = Signal([])

    def monitor_temperature(temps, limit):
        avg_temp = sum(temps) / len(temps)
        print(f"\n🌡️ Current temperatures: {temps}")
        print(f"📊 Average temperature: {avg_temp:.1f}°C")
        print(f"⚠️ Threshold: {limit}°C")

        if avg_temp > limit:
            notification = f"🚨 Warning: Average temperature {avg_temp:.1f}°C exceeds threshold of {limit}°C"
            print(f"{notification}")
            notifications.value = [*notifications.value, notification]

    effect_instance = effect(monitor_temperature)(temperatures, threshold)

    # Test cases
    test_temperatures = [
        [21, 22, 21, 23],  # Avg: 21.75
        [23, 24, 23, 25],  # Avg: 23.75 (exceeds threshold)
        [22, 21, 22, 21],  # Avg: 21.5
    ]

    print("\nMonitoring temperature changes:")
    for temps in test_temperatures:
        print("\nUpdating temperature readings...")
        temperatures.value = temps
        time.sleep(1)

    print("\n📋 Notification History:")
    if notifications.value:
        for note in notifications.value:
            print(f"  {note}")
    else:
        print("  No notifications generated")

    return effect_instance


if __name__ == "__main__":
    example()
