# ABOUTME: A per host rate limiter over an injectable clock, so polite fetching is testable.
# ABOUTME: SystemClock is real time. ManualClock is controllable time, not a mocked collaborator.
import math
import threading
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Real time."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class ManualClock:
    """Time that only moves when told to. Sleeping advances it and is recorded."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds

    def advance(self, seconds: float) -> None:
        self._now += seconds


class HostRateLimiter:
    """Keeps requests to one host at least delay_seconds apart. Hosts are independent.

    A single lock serialises callers, so a sleeping caller also holds back other threads.
    """

    def __init__(self, clock: Clock, delay_seconds: float) -> None:
        if (
            isinstance(delay_seconds, bool)
            or not isinstance(delay_seconds, int | float)
            or not math.isfinite(delay_seconds)
            or delay_seconds < 0
        ):
            raise ValueError("delay_seconds must be a finite number, zero or more")
        self._clock = clock
        self._delay = float(delay_seconds)
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        """Block until the delay since the previous request to this host has passed."""
        key = host.lower()
        with self._lock:
            last = self._last_request.get(key)
            if last is not None:
                remaining = last + self._delay - self._clock.monotonic()
                if remaining > 0:
                    self._clock.sleep(remaining)
            self._last_request[key] = self._clock.monotonic()
