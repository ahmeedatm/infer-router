"""Model pool for the tri-criteria router (Phase 3).

Describes the set of LLM targets the router chooses from. The prototype pool
mirrors chapter 4 of the memoir: a cheap generic model, a strong generic
model, and one domain-specialized model per network domain (ran, core,
security, slice). Cost and latency profiles come from ``app.config`` so that
nothing is hardcoded here; they are relative placeholders to be recalibrated
on real measurements in Phase 5.

This module holds no decision logic: it only builds immutable candidates.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app import config

Tier = Literal["light", "heavy"]


class PoolModel(BaseModel):
    """An immutable LLM target available to the router.

    Attributes:
        model_id: Identifier (OpenRouter model id, possibly domain-suffixed).
        tier: ``light`` (cheap, fast) or ``heavy`` (strong, costly).
        domain: ``None`` for a generic model, else the network domain it is
            specialized on (ran/core/security/slice).
        cost: Estimated per-call cost (>= 0).
        latency_ms: Estimated latency in milliseconds (>= 0).
    """

    model_config = ConfigDict(frozen=True)

    model_id: str
    tier: Tier
    domain: Optional[str] = None
    cost: float = Field(ge=0.0)
    latency_ms: float = Field(ge=0.0)


def _generic_models() -> tuple[PoolModel, ...]:
    """The two generic tiers (light and heavy), profiles from config."""
    light = PoolModel(
        model_id=config.MODEL_LIGHT,
        tier="light",
        domain=None,
        cost=config.POOL_LIGHT_COST,
        latency_ms=config.POOL_LIGHT_LATENCY_MS,
    )
    heavy = PoolModel(
        model_id=config.MODEL_HEAVY,
        tier="heavy",
        domain=None,
        cost=config.POOL_HEAVY_COST,
        latency_ms=config.POOL_HEAVY_LATENCY_MS,
    )
    return (light, heavy)


def _specialized_models() -> tuple[PoolModel, ...]:
    """One specialized model per network domain.

    Prototype choice: each specialist is the heavy base model tagged with a
    domain (``<MODEL_HEAVY>#<domain>``), with the heavy cost/latency profile.
    """
    return tuple(
        PoolModel(
            model_id=f"{config.MODEL_HEAVY}#{domain}",
            tier="heavy",
            domain=domain,
            cost=config.POOL_HEAVY_COST,
            latency_ms=config.POOL_HEAVY_LATENCY_MS,
        )
        for domain in config.POOL_DOMAINS
    )


def default_pool() -> tuple[PoolModel, ...]:
    """Build the prototype pool: light-generic, heavy-generic, 4 specialists.

    Returns a fresh immutable tuple on each call; callers may pass their own
    pool to the router instead of relying on this default.
    """
    return _generic_models() + _specialized_models()
