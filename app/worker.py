from __future__ import annotations

import asyncio
import json
import logging
import time

from redis.asyncio import Redis

from app.aap import run_aap_probe
from app.arrival import get_lambda
from app.config import (
    AAP_WINDOW,
    ACCURATE_MODEL_NAME,
    ACCURATE_MODEL_URL,
    C_COEFFICIENT,
    CLIENT_CALLBACK_URL,
    DEFAULT_SCENARIO,
    FAST_MODEL_NAME,
    FAST_MODEL_URL,
    OMEGA,
    QUEUE_BACKEND,
    ROUTING_STRATEGY,
    TAU,
)
from app.redis_keys import (
    ACCURACY_KEY_PREFIX,
    PUSH_LATENCY_KEY_PREFIX,
)
from app.result_store import store_result
from app.gpp import rank_models
from app.inference import call_model
from app.mu import compute_and_store_mu, get_mu, record_latency
from app.queue.base import QueueBackend
from app.threshold import decide_k, get_k_active

logger = logging.getLogger(__name__)

_ALL_MODELS: list[tuple[str, str]] = [
    (ACCURATE_MODEL_NAME, ACCURATE_MODEL_URL),
    (FAST_MODEL_NAME, FAST_MODEL_URL),
]


async def _route_infer_router(
    redis_client: Redis,
    queue_length: int,
    mu_fast: float,
    mu_accurate: float,
    lambda_: float,
) -> tuple[str, str, str, int]:
    """Run the full InferRouter routing pipeline.

    Returns (model_name, model_url, routing_reason, k_active).
    """
    k_active = await decide_k(
        redis_client, queue_length, mu_fast, mu_accurate, lambda_, TAU
    )

    if k_active == 1:
        return ACCURATE_MODEL_NAME, ACCURATE_MODEL_URL, "infer_k1_gold", k_active

    # k_active == 2: use GPP to pick the best model
    fast_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{FAST_MODEL_NAME}")
    fast_acc = float(fast_raw) if fast_raw is not None else 0.5
    # Le modèle gold (Accurate) a alpha = 0 par convention, sa précision mesurée
    # n'entre pas dans le calcul ci-dessous.

    alphas = {
        ACCURATE_MODEL_NAME: 0.0,               # gold standard: alpha = 0
        FAST_MODEL_NAME: max(0.0, 1.0 - fast_acc),
    }
    mus = {FAST_MODEL_NAME: mu_fast, ACCURATE_MODEL_NAME: mu_accurate}

    ranked = rank_models(_ALL_MODELS, alphas, mus, C_COEFFICIENT, OMEGA)
    best = ranked[0]

    reason = (
        "infer_k2_accurate" if best.name == ACCURATE_MODEL_NAME else "infer_k2_fast"
    )
    return best.name, best.url, reason, k_active


def _build_result_dict(
    data: dict,
    model_used: str,
    queue_length: int,
    scenario: str,
    model_result: dict,
    routing_reason: str,
    k_active: int,
    lambda_at_decision: float,
) -> dict:
    now = time.time()
    enqueued_at = data.get("timestamp")
    e2e_latency = round(now - enqueued_at, 4) if enqueued_at else None
    return {
        "sensor_id": data["sensor_id"],
        "model": model_used,
        "latency": model_result["latency"],
        "e2e_latency": e2e_latency,
        "queue_at_start": queue_length,
        "scenario": scenario,
        "processed_at": round(now, 3),
        "accuracy": model_result["accuracy"],
        "routing_reason": routing_reason,
        "image_size": data.get("image_size"),
        "k_active": k_active,
        "lambda_at_decision": lambda_at_decision,
        "queue_backend": QUEUE_BACKEND,
        "queue_push_latency_ms": data.get("_push_latency_ms"),
    }


async def process_inference(redis_client: Redis, queue: QueueBackend) -> None:
    logger.info(
        "InferRouter worker started (routing_strategy=%s queue_backend=%s)",
        ROUTING_STRATEGY, QUEUE_BACKEND,
    )

    while True:
        try:
            data_json = await queue.pop()
            if data_json is None:
                continue

            try:
                data = json.loads(data_json)
            except json.JSONDecodeError as exc:
                logger.error("Malformed JSON skipped: %s", exc)
                continue

            scenario = data.get("scenario", DEFAULT_SCENARIO)
            queue_length = await queue.length()

            # Retrieve push latency stored by main.py (fire-and-forget delete)
            sensor_id = data.get("sensor_id", "")
            push_key = f"{PUSH_LATENCY_KEY_PREFIX}:{sensor_id}"
            raw_push = await redis_client.getdel(push_key)
            data["_push_latency_ms"] = float(raw_push) if raw_push else None

            # Read cached metrics (updated by background tasks and previous iterations)
            mu_fast = await get_mu(redis_client, FAST_MODEL_NAME)
            mu_accurate = await get_mu(redis_client, ACCURATE_MODEL_NAME)
            lambda_ = await get_lambda(redis_client)

            # --- Routing decision ---
            if ROUTING_STRATEGY == "always-fast":
                model_used, model_url, routing_reason = (
                    FAST_MODEL_NAME, FAST_MODEL_URL, "static_fast"
                )
                k_active = await get_k_active(redis_client)
            elif ROUTING_STRATEGY == "always-accurate":
                model_used, model_url, routing_reason = (
                    ACCURATE_MODEL_NAME, ACCURATE_MODEL_URL, "static_accurate"
                )
                k_active = await get_k_active(redis_client)
            else:
                # infer-router: full algorithm
                model_used, model_url, routing_reason, k_active = (
                    await _route_infer_router(
                        redis_client, queue_length, mu_fast, mu_accurate, lambda_
                    )
                )

            # --- Inference ---
            model_result = await call_model(model_url, data["image"], CLIENT_CALLBACK_URL)

            # --- Update service rate metrics ---
            await record_latency(redis_client, model_used, model_result["latency"])
            await compute_and_store_mu(redis_client, model_used)

            # Refresh mu after update
            mu_fast = await get_mu(redis_client, FAST_MODEL_NAME)
            mu_accurate = await get_mu(redis_client, ACCURATE_MODEL_NAME)

            # Stability check
            if lambda_ > 0 and (mu_fast + mu_accurate) < lambda_:
                logger.warning(
                    "System unstable: sum(μ)=%.3f < λ=%.3f",
                    mu_fast + mu_accurate,
                    lambda_,
                )

            # --- AAP probe (fire-and-forget, only for gold-standard inference) ---
            if ROUTING_STRATEGY == "infer-router" and model_used == ACCURATE_MODEL_NAME:
                asyncio.create_task(
                    run_aap_probe(
                        redis_client,
                        data["image"],
                        model_result.get("results"),
                        AAP_WINDOW,
                        CLIENT_CALLBACK_URL,
                    )
                )

            # --- Store result ---
            raw_acc = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{model_used}")
            model_result = {
                **model_result,
                "accuracy": float(raw_acc) if raw_acc is not None else None,
            }

            result_dict = _build_result_dict(
                data, model_used, queue_length, scenario, model_result,
                routing_reason, k_active, lambda_,
            )

            await store_result(redis_client, scenario, result_dict)

            logger.info(
                "[%s] %s | latency=%.2fs queue=%d k=%d λ=%.2f μf=%.2f μa=%.2f reason=%s",
                scenario, model_used, result_dict["latency"], queue_length,
                k_active, lambda_, mu_fast, mu_accurate, routing_reason,
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Worker error, retrying: %s", exc, exc_info=True)
            await asyncio.sleep(0.1)
