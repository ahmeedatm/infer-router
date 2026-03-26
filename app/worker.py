from __future__ import annotations

import asyncio
import json
import logging
import time

from redis.asyncio import Redis

from app.config import (
    ACCURATE_MODEL_NAME,
    ACCURATE_MODEL_URL,
    ACCURACY_KEY_PREFIX,
    ACCURACY_PENALTY_THRESHOLD,
    CLIENT_CALLBACK_URL,
    DEFAULT_SCENARIO,
    FAST_MODEL_NAME,
    FAST_MODEL_URL,
    INFERENCE_QUEUE_KEY,
    QUEUE_THRESHOLD,
    RESULTS_KEY_PREFIX,
    RESULTS_MAX_LEN,
    THRESHOLD_REDIS_KEY,
)
from app.inference import call_model

logger = logging.getLogger(__name__)


async def _select_model(
    redis_client: Redis, queue_length: int, threshold: int
) -> tuple[str, str, str]:
    """Returns (model_name, model_url, routing_reason)."""
    queue_pressured = queue_length >= threshold

    fast_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{FAST_MODEL_NAME}")
    accurate_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{ACCURATE_MODEL_NAME}")
    fast_acc = float(fast_raw) if fast_raw is not None else None
    accurate_acc = float(accurate_raw) if accurate_raw is not None else None

    if queue_pressured:
        if fast_acc is not None and accurate_acc is not None:
            if (accurate_acc - fast_acc) > ACCURACY_PENALTY_THRESHOLD:
                return ACCURATE_MODEL_NAME, ACCURATE_MODEL_URL, "accuracy_override"
        reason = "queue_pressure" if fast_acc is not None else "fallback"
        return FAST_MODEL_NAME, FAST_MODEL_URL, reason
    return ACCURATE_MODEL_NAME, ACCURATE_MODEL_URL, "low_queue"


def _build_result_dict(
    data: dict,
    model_used: str,
    queue_length: int,
    scenario: str,
    model_result: dict,
    routing_reason: str,
) -> dict:
    return {
        "sensor_id": data["sensor_id"],
        "model": model_used,
        "latency": model_result["latency"],
        "queue_at_start": queue_length,
        "scenario": scenario,
        "processed_at": round(time.time(), 3),
        "accuracy": model_result["accuracy"],
        "routing_reason": routing_reason,
        "image_size": data.get("image_size"),
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
                continue

            scenario = data.get("scenario", DEFAULT_SCENARIO)
            queue_length = await redis_client.llen(INFERENCE_QUEUE_KEY)

            raw_threshold = await redis_client.get(THRESHOLD_REDIS_KEY)
            threshold = int(raw_threshold) if raw_threshold is not None else QUEUE_THRESHOLD

            model_used, model_url, routing_reason = await _select_model(redis_client, queue_length, threshold)

            model_result = await call_model(model_url, data["image"], CLIENT_CALLBACK_URL)

            raw_acc = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{model_used}")
            model_result = {**model_result, "accuracy": float(raw_acc) if raw_acc is not None else None}

            result_dict = _build_result_dict(data, model_used, queue_length, scenario, model_result, routing_reason)

            results_key = f"{RESULTS_KEY_PREFIX}:{scenario}"
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lpush(results_key, json.dumps(result_dict))
                pipe.ltrim(results_key, 0, RESULTS_MAX_LEN - 1)
                await pipe.execute()

            logger.info(
                "[%s] %s | latency=%.2fs queue=%d reason=%s accuracy=%s",
                scenario,
                model_used,
                result_dict["latency"],
                queue_length,
                routing_reason,
                result_dict["accuracy"],
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Worker error, retrying: %s", exc, exc_info=True)
            await asyncio.sleep(0.1)
