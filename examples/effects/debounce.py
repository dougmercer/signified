import time
from threading import Timer
from typing import Callable

from signified import Signal, effect


def debounce(wait_time: float) -> Callable:
    """
    Creates a debounced version of a function that only executes after wait_time seconds
    of no new calls.
    """

    def decorator(fn: Callable) -> Callable:
        def debounced(*args, **kwargs):
            def call_fn():
                fn(*args, **kwargs)

            timer = Timer(wait_time, call_fn)
            timer.start()

            # Return cleanup function
            def cleanup():
                timer.cancel()

            return cleanup

        return debounced

    return decorator


def debounced_search():
    """
    Demonstrates a debounced search using effects.

    This will only perform the search after the user stops typing for 0.5 seconds.
    """
    search_query = Signal("")
    search_results = Signal([])

    @debounce(wait_time=0.5)
    def perform_search(query: str):
        """Actually performs the search after debounce period"""
        if not query:
            search_results.value = []
            print("🔍 Search cleared")
            return

        print(f"\n🔍 Performing search for: '{query}'")

        results = [f"📚 Python tutorial: {query}", f"💻 Code example: {query}", f"📖 Documentation: {query}"]
        search_results.value = results

        print("Results found:")
        for result in results:
            print(f"  {result}")

    # Create effect that watches search_query
    effect_instance = effect(perform_search)(search_query)

    # Demonstrate rapid search changes
    print("\nTyping 'python' quickly:")
    for query in ["p", "py", "pyt", "pyth", "pytho", "python"]:
        print(f"⌨️  User typed: '{query}'")
        search_query.value = query
        time.sleep(0.1)  # Simulate fast typing

    # Wait to see final results
    print("\nWe will only see one round of search results")
    time.sleep(1)

    # Clear the query
    search_query.value = ""
    time.sleep(1)

    print("\nTyping 'flask' with pauses:")
    print("\nWe will only see one result for each button press")
    for query in ["f", "fl", "fla", "flas", "flask"]:
        print(f"⌨️  User typed: '{query}'")
        search_query.value = query
        time.sleep(0.6)  # Simulate slower typing

    return effect_instance


if __name__ == "__main__":
    debounced_search()
