"""Anti-Idling Accuracy Profiling (AAP).

When Accurate-Model (gold standard) finishes an inference, this module
probes the Fast-Model with the same image — but only if Fast-Model is idle
enough (mu_fast >= lambda_). The probe result is compared to the gold output
to compute an accuracy score maintained in a sliding window.

This runs as a fire-and-forget asyncio.create_task, so it never delays
the main inference path.

Reference: Section IV-A of the IEEE paper.
"""
from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.arrival import get_lambda
from app.config import (
    FAST_MODEL_NAME,
    FAST_MODEL_URL,
)
from app.inference import call_model
from app.mu import get_mu
from app.redis_keys import ACCURACY_KEY_PREFIX, AAP_WINDOW_KEY_PREFIX

logger = logging.getLogger(__name__)


def _compare_results(gold_result: object, candidate_result: object) -> bool:
    """Return True if candidate output agrees with the gold standard.

    When the model API exposes detection results (bounding boxes, class labels),
    this should compare detected class sets or use IoU matching.
    In the current deployment the model containers return only timing metadata
    (no bounding boxes), so exact string comparison is meaningless — we treat
    any successful response as a match, which is the correct default for a
    latency-focused PoC where AAP is used to probe availability rather than
    semantic accuracy.
    """
    # If both models returned a result dict, treat it as a match.
    # TODO: replace with IoU / class-label comparison when model API exposes detections.
    if gold_result is None and candidate_result is None:
        return True
    if gold_result is None or candidate_result is None:
        return False
    return True


async def _update_accuracy_window(
    redis: Redis,
    model_name: str,
    match: bool,
    window: int,
) -> None:
    """Append match result (1/0) to the rolling window, recompute accuracy."""
    key = f"{AAP_WINDOW_KEY_PREFIX}:{model_name}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lpush(key, "1" if match else "0")
        pipe.ltrim(key, 0, window - 1)
        await pipe.execute()

    raw = await redis.lrange(key, 0, -1)
    if raw:
        accuracy = sum(int(v) for v in raw) / len(raw)
        await redis.set(f"{ACCURACY_KEY_PREFIX}:{model_name}", str(round(accuracy, 4)))
        logger.debug(
            "AAP: %s accuracy updated to %.4f (%d/%d matches)",
            model_name, accuracy, int(accuracy * len(raw)), len(raw),
        )


async def run_aap_probe(
    redis: Redis,
    image_b64: str,
    gold_result: object,
    aap_window: int,
    callback_url: str = "",
) -> None:
    """Probe Fast-Model if idle; compare result to gold; update accuracy window.

    Designed to be called as asyncio.create_task — exceptions are caught
    and logged so they never surface to the worker's main loop.
    """
    try:
        lambda_ = await get_lambda(redis)
        mu_fast = await get_mu(redis, FAST_MODEL_NAME)

        if mu_fast < lambda_:
            logger.debug(
                "AAP: Fast-Model busy (mu=%.3f < λ=%.3f), skipping probe",
                mu_fast, lambda_,
            )
            return

        candidate = await call_model(FAST_MODEL_URL, image_b64, callback_url)
        match = _compare_results(gold_result, candidate.get("results"))
        await _update_accuracy_window(redis, FAST_MODEL_NAME, match, aap_window)

    except Exception as exc:
        logger.warning("AAP probe failed: %s", exc)
