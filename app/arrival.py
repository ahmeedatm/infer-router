"""Sliding-window arrival rate (λ) tracker.

Each arrival is recorded as a timestamped entry in a Redis sorted set.
A background task recomputes lambda every second and caches it to Redis.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from redis.asyncio import Redis

from app.redis_keys import ARRIVALS_KEY, LAMBDA_KEY

logger = logging.getLogger(__name__)

LAMBDA_WINDOW_S: float = 5.0  # TODO: move to config.py in Task 2


async def record_arrival(redis: Redis) -> None:
    """Record one request arrival. Call on every LPUSH in POST /new_pod_run_model."""
    now = time.time()
    member = str(uuid.uuid4())
    await redis.zadd(ARRIVALS_KEY, {member: now})
    await redis.zremrangebyscore(ARRIVALS_KEY, "-inf", now - LAMBDA_WINDOW_S)


async def _compute_lambda(redis: Redis) -> float:
    now = time.time()
    count = await redis.zcount(ARRIVALS_KEY, now - LAMBDA_WINDOW_S, now)
    return round(count / LAMBDA_WINDOW_S, 4)


async def lambda_updater(redis: Redis) -> None:
    """Background task: recompute and store lambda every second."""
    while True:
        try:
            lam = await _compute_lambda(redis)
            await redis.set(LAMBDA_KEY, str(lam))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("lambda_updater error: %s", exc)
        await asyncio.sleep(1.0)


async def get_lambda(redis: Redis) -> float:
    """Return cached lambda value (req/s). Returns 0.0 if not yet computed."""
    raw = await redis.get(LAMBDA_KEY)
    return float(raw) if raw else 0.0
