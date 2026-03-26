"""Abstract queue backend interface.

Only the inference queue operations are abstracted here:
  push()   — enqueue a serialized request
  pop()    — dequeue (blocking with 1s timeout)
  length() — current queue depth
  close()  — release resources

Everything else (results, accuracy, metrics) stays on Redis directly.
"""
from __future__ import annotations

from typing import Protocol


class QueueBackend(Protocol):
    async def push(self, data: str) -> float:
        """Enqueue serialized data. Returns push duration in milliseconds."""
        ...

    async def pop(self) -> str | None:
        """Dequeue one item. Blocks up to 1s, returns None on timeout."""
        ...

    async def length(self) -> int:
        """Return current number of items in the queue."""
        ...

    async def close(self) -> None:
        """Release any backend-specific resources."""
        ...
