from __future__ import annotations

import asyncio
import json
import logging
import time

from redis.asyncio import Redis

from app.config import (
    ACCURATE_MODEL_LATENCY,
    ACCURATE_MODEL_NAME,
    ACCURACY_KEY_PREFIX,
    ACCURACY_PENALTY_THRESHOLD,
    DEFAULT_SCENARIO,
    FAST_MODEL_LATENCY,
    FAST_MODEL_NAME,
    INFERENCE_QUEUE_KEY,
    QUEUE_THRESHOLD,
    RESULTS_KEY_PREFIX,
    RESULTS_MAX_LEN,
)

logger = logging.getLogger(__name__)


async def _select_model(
    redis_client: Redis, queue_length: int
) -> tuple[str, float, str]:
    """Returns (model_name, processing_time, routing_reason)."""
    queue_pressured = queue_length >= QUEUE_THRESHOLD

    fast_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{FAST_MODEL_NAME}")
    accurate_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{ACCURATE_MODEL_NAME}")
    fast_acc = float(fast_raw) if fast_raw is not None else None
    accurate_acc = float(accurate_raw) if accurate_raw is not None else None

    if queue_pressured:
        if fast_acc is not None and accurate_acc is not None:
            if (accurate_acc - fast_acc) > ACCURACY_PENALTY_THRESHOLD:
                return ACCURATE_MODEL_NAME, ACCURATE_MODEL_LATENCY, "accuracy_override"
        reason = "queue_pressure" if fast_acc is not None else "fallback"
        return FAST_MODEL_NAME, FAST_MODEL_LATENCY, reason
    return ACCURATE_MODEL_NAME, ACCURATE_MODEL_LATENCY, "low_queue"


def _build_result_dict(
    data: dict,
    model_used: str,
    queue_length: int,
    scenario: str,
    accuracy: float | None,
    routing_reason: str,
) -> dict:
    return {
        "sensor_id": data["sensor_id"],
        "model": model_used,
        "latency": round(time.time() - data["timestamp"], 4),
        "queue_at_start": queue_length,
        "scenario": scenario,
        "processed_at": round(time.time(), 3),
        "accuracy": accuracy,
        "routing_reason": routing_reason,
    }


async def process_inference(redis_client: Redis) -> None:
    logger.info("InferRouter worker started (threshold=%d)", QUEUE_THRESHOLD)

    while True:
        try:
            result = await redis_client.brpop(INFERENCE_QUEUE_KEY)
            if result is None:
                continue

            _, data_json = result

            try:
                data = json.loads(data_json)
            except json.JSONDecodeError as exc:
                logger.error("Malformed JSON skipped: %s", exc)
                continue  # Bug fix 2: skip bad messages instead of crashing

            scenario = data.get("scenario", DEFAULT_SCENARIO)
            queue_length = await redis_client.llen(INFERENCE_QUEUE_KEY)

            model_used, processing_time, routing_reason = await _select_model(redis_client, queue_length)

            await asyncio.sleep(processing_time)

            raw_acc = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{model_used}")
            model_accuracy = float(raw_acc) if raw_acc is not None else None

            result_dict = _build_result_dict(data, model_used, queue_length, scenario, model_accuracy, routing_reason)

            results_key = f"{RESULTS_KEY_PREFIX}:{scenario}"
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lpush(results_key, json.dumps(result_dict))
                pipe.ltrim(results_key, 0, RESULTS_MAX_LEN - 1)
                await pipe.execute()  # Bug fix 3: atomic LPUSH+LTRIM caps list

            logger.info(
                "[%s] %s | latency=%.2fs queue=%d reason=%s",
                scenario,
                model_used,
                result_dict["latency"],
                queue_length,
                routing_reason,
            )

        except asyncio.CancelledError:
            raise  # propagate for clean shutdown
        except Exception as exc:
            logger.error("Worker error, retrying: %s", exc, exc_info=True)
            await asyncio.sleep(0.1)
