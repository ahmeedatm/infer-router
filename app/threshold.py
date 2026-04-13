"""Waiting-Based Threshold Control (3-state FSM).

Computes expected waiting time w(k) and transitions k_active between 1 and 2.

Formula (Section IV-C of the paper):
    w(k) = (x - 1) / (2 * mu_k) + tau / (1 + exp(mu_k - lambda_))

where:
    x       = current queue length
    k       = number of active models
    mu_k    = average service rate across k active models (req/s)
    lambda_ = current arrival rate (req/s)
    tau     = SLA waiting-time budget (seconds)

State machine (2-model system: k in {1, 2}):
    k=2 and w(k=1) <= tau  →  scale-down to k=1
    w(k_current) > tau     →  scale-up   to k+1 (capped at K_MAX=2)
    otherwise              →  maintain   k_current
"""
from __future__ import annotations

import logging
import math

from redis.asyncio import Redis

from app.config import K_MAX, K_MIN
from app.redis_keys import K_ACTIVE_KEY

logger = logging.getLogger(__name__)


def compute_waiting_time(
    queue_length: int,
    mu_k: float,
    lambda_: float,
    tau: float,
) -> float:
    """Compute expected waiting time w(k).

    Returns inf if mu_k <= 0 (no service rate data yet).
    """
    if mu_k <= 0:
        return float("inf")
    x = max(queue_length, 1)
    return (x - 1) / (2 * mu_k) + tau / (1 + math.exp(mu_k - lambda_))


async def get_k_active(redis: Redis) -> int:
    """Return current number of active models. Defaults to K_MAX on cold start."""
    raw = await redis.get(K_ACTIVE_KEY)
    return int(raw) if raw else K_MAX


async def set_k_active(redis: Redis, k: int) -> None:
    await redis.set(K_ACTIVE_KEY, str(k))


async def decide_k(
    redis: Redis,
    queue_length: int,
    mu_fast: float,
    mu_accurate: float,
    lambda_: float,
    tau: float,
) -> int:
    """Run the 3-state FSM and return the new k_active value.

    k=1: only Accurate-Model (gold standard) handles traffic.
    k=2: both models are eligible; GPP selects which to use.

    mu for k models:
        k=1 → mu_1 = mu_accurate
        k=2 → mu_2 = (mu_accurate + mu_fast) / 2
    """
    k_current = await get_k_active(redis)

    mu_1 = mu_accurate
    mu_2 = (mu_accurate + mu_fast) / 2 if mu_fast > 0 else mu_accurate

    mu_k = mu_2 if k_current == 2 else mu_1
    w_k = compute_waiting_time(queue_length, mu_k, lambda_, tau)

    # Scale-down: check if k-1 models would still meet SLA
    if k_current == K_MAX:
        w_k_minus = compute_waiting_time(queue_length, mu_1, lambda_, tau)
        if w_k_minus <= tau:
            if k_current != K_MIN:
                logger.info(
                    "Threshold FSM: scale-down %d→%d (w(k-1)=%.3fs ≤ τ=%.3fs)",
                    k_current, K_MIN, w_k_minus, tau,
                )
                await set_k_active(redis, K_MIN)
            return K_MIN

    # Scale-up: current k cannot meet SLA
    if w_k > tau:
        new_k = min(k_current + 1, K_MAX)
        if new_k != k_current:
            logger.info(
                "Threshold FSM: scale-up %d→%d (w(k)=%.3fs > τ=%.3fs)",
                k_current, new_k, w_k, tau,
            )
            await set_k_active(redis, new_k)
        return new_k

    # Maintain
    return k_current
