from __future__ import annotations

import datetime
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List
from weakref import WeakValueDictionary

from signified import Signal, Variable, unref
from signified.plugins import hookimpl, pm


class EventType(Enum):
    READ = auto()
    WRITE = auto()
    CREATE = auto()


@dataclass
class AccessEvent:
    """Represents a single access to a reactive value."""

    timestamp: datetime.datetime
    event_type: EventType
    value: Any


@dataclass
class AccessStats:
    read_count: int = 0
    write_count: int = 0
    creation_time: datetime.datetime = field(default_factory=datetime.datetime.now)
    last_access_time: datetime.datetime = field(default_factory=datetime.datetime.now)
    value_history: List[AccessEvent] = field(default_factory=list, repr=False)  # Rename to be clearer

    def add_event(self, event_type: EventType, value: Any) -> None:
        now = datetime.datetime.now()

        if event_type == EventType.READ:
            self.read_count += 1
            self.last_access_time = now
        elif event_type in (EventType.WRITE, EventType.CREATE):
            if event_type == EventType.WRITE:
                self.write_count += 1
            elif event_type == EventType.CREATE:
                self.creation_time = now
            self.last_access_time = now
            self.value_history.append(AccessEvent(now, event_type, value))

    @property
    def total_accesses(self) -> int:
        """Total number of reads and modifications."""
        return self.read_count + self.write_count

    @property
    def last_value(self) -> Any:
        """Most recently recorded value."""
        return self.value_history[-1].value if self.value_history else None


class AccessTracker:
    """Plugin for tracking reactive value access patterns."""

    def __init__(self):
        self.stats: Dict[int, AccessStats] = defaultdict(AccessStats)
        self._variables: WeakValueDictionary[int, Variable[Any]] = WeakValueDictionary()

    def cleanup(self) -> None:
        """Clear stats."""
        self.stats.clear()
        self._variables.clear()

    @hookimpl
    def created(self, value: Variable[Any]) -> None:
        """Track creation of new reactive values."""
        self.stats[id(value)].add_event(EventType.CREATE, unref(value))
        self._variables[id(value)] = value

    @hookimpl
    def updated(self, value: Variable[Any]) -> None:
        """Track modifications to reactive values."""
        self.stats[id(value)].add_event(EventType.WRITE, unref(value))

    @hookimpl
    def read(self, value: Variable[Any]) -> None:
        """Record a read access to a reactive value."""
        self.stats[id(value)].add_event(EventType.READ, unref(value))

    def get_stats(self, value: Variable[Any]) -> AccessStats:
        """Get access statistics for a specific reactive value."""
        return self.stats[id(value)]

    def print_summary(self) -> None:
        """Print summary statistics for all tracked values."""
        print("\nAccess Pattern Summary:")
        print("-" * 50)
        for value_id, stats in self.stats.items():
            value = self._variables.get(value_id)
            print(f"Value {value:n}:")
            print(f"\tReads: {stats.read_count}")
            print(f"\tModifications: {stats.write_count}")
            print(f"\tTotal accesses: {stats.total_accesses}")
            if stats.creation_time and stats.last_access_time:
                lifetime = stats.last_access_time - stats.creation_time
                print(f"\tLifetime: {lifetime.total_seconds():.2f} seconds")
            print()


# Create global tracker instance
tracker = AccessTracker()

# Register it
pm.register(tracker)

if __name__ == "__main__":
    import time

    # Create some reactive values and use them
    x = Signal(1).add_name("x")
    y = Signal(2).add_name("y")

    time.sleep(1)

    # Some modifications
    x.value = 10  # x read and write
    y.value = 20  # y read and write
    x.value = 30  # x read and write

    # More reads
    z = (x + y).add_name("z")  # x and y read

    # Wait a bit to get some time differences
    time.sleep(1)

    # Print stats
    tracker.print_summary()

    # Get specific stats
    print(f"Value history for x: {[v.value for v in tracker.get_stats(x).value_history]}")
    print(f"Value history for y: {[v.value for v in tracker.get_stats(y).value_history]}")
    print(f"Value history for z: {[v.value for v in tracker.get_stats(z).value_history]}")

    # Cleanup
    pm.unregister(tracker)
    tracker.cleanup()
