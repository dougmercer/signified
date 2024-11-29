import logging
from typing import Any, Callable, Optional

from signified import Signal, Variable, register_global_callback


class ReactiveLogger:
    """A logger for tracking reactive value creation and updates."""

    def __init__(self, logger: logging.Logger) -> None:
        """Initialize the reactive logger.

        Args:
            level: The logging level to use (default: logging.INFO)
        """
        self.logger = logger

    def __call__(self, reactive_value: Variable[Any, Any]) -> Optional[Callable[[], None]]:
        """Create an effect that logs reactive value creation and updates.

        Args:
            reactive_value: The reactive value to monitor

        Returns:
            A cleanup function
        """
        # Log creation
        value_type = type(reactive_value).__name__
        value_id = id(reactive_value)

        self.logger.info(f"Created {value_type}(id={value_id}) with value: {reactive_value.value}")

        # Create an observer that logs updates
        class LogUpdateObserver:
            logger = self.logger

            def update(self) -> None:
                self.logger.info(f"Updated {value_type}(id={value_id}) to value: {reactive_value.value}")

        # Subscribe the  observer
        observer = LogUpdateObserver()
        reactive_value.subscribe(observer)

        def cleanup() -> None:
            reactive_value.unsubscribe(observer)
            self.logger.debug(f"Cleaned up {value_type}(id={value_id})")

        return cleanup


# Configure a basic logger
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Register it as a global callback, added to every Signal/Computed created.
register_global_callback(ReactiveLogger(logger))

# Do stuff with reactive values
x = Signal(1)
y = x + 2
x.value = 19
x.value = 2
z = x - y
x.value = 12
