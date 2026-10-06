"""Injectable time source so time-dependent logic stays deterministic in tests."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current time as a UTC-aware datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
