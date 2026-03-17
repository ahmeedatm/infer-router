import asyncio
import json
import logging
import time

from redis.asyncio import Redis

from app.config import (
    ACCURATE_MODEL_LATENCY,
    ACCURATE_MODEL_NAME,
    DEFAULT_SCENARIO,
    FAST_MODEL_LATENCY,
    FAST_MODEL_NAME,
    INFERENCE_QUEUE_KEY,
    QUEUE_THRESHOLD,
    RESULTS_KEY_PREFIX,
    RESULTS_MAX_LEN,
)

logger = logging.getLogger(__name__)


def _build_result_dict(data: dict, model_used: str, queue_length: int, scenario: str) -> dict:
    return {
        "sensor_id": data["sensor_id"],
        "model": model_used,
        "latency": round(time.time() - data["timestamp"], 4),
        "queue_at_start": queue_length,
        "scenario": scenario,
        "processed_at": round(time.time(), 3),
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

            if queue_length >= QUEUE_THRESHOLD:  # Bug fix 1: >= not >
                model_used = FAST_MODEL_NAME
                processing_time = FAST_MODEL_LATENCY
            else:
                model_used = ACCURATE_MODEL_NAME
                processing_time = ACCURATE_MODEL_LATENCY

            await asyncio.sleep(processing_time)

            result_dict = _build_result_dict(data, model_used, queue_length, scenario)

            results_key = f"{RESULTS_KEY_PREFIX}:{scenario}"
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lpush(results_key, json.dumps(result_dict))
                pipe.ltrim(results_key, 0, RESULTS_MAX_LEN - 1)
                await pipe.execute()  # Bug fix 3: atomic LPUSH+LTRIM caps list

            logger.info(
                "[%s] %s | latency=%.2fs queue=%d",
                scenario,
                model_used,
                result_dict["latency"],
                queue_length,
            )

        except asyncio.CancelledError:
            raise  # propagate for clean shutdown
        except Exception as exc:
            logger.error("Worker error, retrying: %s", exc, exc_info=True)
            await asyncio.sleep(0.1)
