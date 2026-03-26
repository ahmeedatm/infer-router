"""Per-model service rate (μ) tracker.

Stores the last MU_WINDOW latency samples per model in a Redis list.
Computes mu = 1 / mean(latency) after each inference and caches it.
"""
from __future__ import annotations

import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

MU_WINDOW: int = 50
LATENCIES_KEY_PREFIX: str = "metrics:latencies"
MU_KEY_PREFIX: str = "metrics:mu"


async def record_latency(redis: Redis, model_name: str, latency: float) -> None:
    """Append latency sample to the model's rolling window in Redis."""
    key = f"{LATENCIES_KEY_PREFIX}:{model_name}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lpush(key, str(latency))
        pipe.ltrim(key, 0, MU_WINDOW - 1)
        await pipe.execute()


async def compute_and_store_mu(redis: Redis, model_name: str) -> float:
    """Compute mu = 1/mean(latency) from the rolling window, store it, return it."""
    key = f"{LATENCIES_KEY_PREFIX}:{model_name}"
    raw_list = await redis.lrange(key, 0, -1)
    if not raw_list:
        return 0.0
    latencies = [float(v) for v in raw_list]
    mean_latency = sum(latencies) / len(latencies)
    mu = 1.0 / mean_latency if mean_latency > 0 else 0.0
    await redis.set(f"{MU_KEY_PREFIX}:{model_name}", str(round(mu, 4)))
    return mu


async def get_mu(redis: Redis, model_name: str) -> float:
    """Return cached mu value for a model (req/s). Returns 0.0 if not yet computed."""
    raw = await redis.get(f"{MU_KEY_PREFIX}:{model_name}")
    return float(raw) if raw else 0.0
