"""Tiny non-blocking concurrency cap for CPU-heavy endpoints (nesting)."""
import threading


class SlotLimiter:
    """`acquire()` never waits: it answers immediately, so an overloaded server returns
    503 `busy` (clients retry) instead of piling up threads that all slow each other down."""

    def __init__(self, slots: int) -> None:
        self.slots = max(0, slots)
        self._sem = threading.BoundedSemaphore(self.slots) if self.slots else None

    def acquire(self) -> bool:
        return bool(self._sem and self._sem.acquire(blocking=False))

    def release(self) -> None:
        if self._sem:
            self._sem.release()
