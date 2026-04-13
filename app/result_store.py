"""Persist an inference result dict to Redis.

Extracted from worker.py so the storage concern is separate from the
routing loop. Future LLM results (with quality scores, prompt metadata)
will be stored here without modifying the worker.
"""
from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.config import RESULTS_MAX_LEN
from app.redis_keys import RESULTS_KEY_PREFIX


async def store_result(redis: Redis, scenario: str, result_dict: dict[str, Any]) -> None:
    """LPUSH result_dict into the scenario list, trimmed to RESULTS_MAX_LEN."""
    key = f"{RESULTS_KEY_PREFIX}:{scenario}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lpush(key, json.dumps(result_dict))
        pipe.ltrim(key, 0, RESULTS_MAX_LEN - 1)
        await pipe.execute()
