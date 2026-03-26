"""Redis-backed queue implementation.

Wraps LPUSH / BRPOP / LLEN on a single Redis list key.
The Redis client lifecycle is managed externally (by main.py lifespan).
"""
from __future__ import annotations

import time

from redis.asyncio import Redis


class RedisQueueBackend:
    def __init__(self, redis: Redis, queue_key: str) -> None:
        self._redis = redis
        self._key = queue_key

    async def push(self, data: str) -> float:
        """LPUSH data onto the queue. Returns push duration in ms."""
        t0 = time.monotonic()
        await self._redis.lpush(self._key, data)
        return (time.monotonic() - t0) * 1000

    async def pop(self) -> str | None:
        """BRPOP with 1s timeout. Returns message string or None."""
        result = await self._redis.brpop(self._key, timeout=1)
        if result is None:
            return None
        _, value = result
        return value.decode() if isinstance(value, bytes) else value

    async def length(self) -> int:
        """LLEN — current queue depth."""
        return await self._redis.llen(self._key)

    async def close(self) -> None:
        """No-op: Redis client is closed by main.py lifespan."""
