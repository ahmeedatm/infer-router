"""Expected-quality policy for the tri-criteria router (Phase 3).

At runtime the router does NOT call every model to observe its quality. It
estimates, per candidate, the quality it would *expect* from a policy
heuristic driven by the model profile, the estimated complexity, and the
intent domain. ``router.select`` then picks the best admissible candidate.

This is a prototype heuristic, deliberately coarse. It is meant to be
recalibrated by the local LLM-Judge in Phase 5 (offline), which will replace
these hand-set constants with measured quality. The bareme lives in
``app.config`` so it can be tuned without touching this module.

Bareme (all values in [0, 1], from config):
    - Specialist ON the intent domain -> QUALITY_SPECIALIST_ON_DOMAIN (strong,
      flat across complexity: domain expertise carries even hard intents).
    - Heavy generic -> QUALITY_HEAVY_GENERIC (good general quality, flat).
    - Specialist OFF its domain -> QUALITY_SPECIALIST_OFF_DOMAIN (no domain
      bonus, behaves like a heavy generic since it is the same base model).
    - Light generic -> QUALITY_LIGHT_BASE on ``simple``, minus
      QUALITY_LIGHT_COMPLEXITY_PENALTY for each complexity rank above simple
      (so it degrades on ``medium`` and further on ``complex``).
"""
from __future__ import annotations

from app import config
from app.llm.pool import PoolModel

# Complexity rank: how far above ``simple`` a label sits (penalty multiplier).
_COMPLEXITY_RANK = {"simple": 0, "medium": 1, "complex": 2}


def _clamp_unit(value: float) -> float:
    """Clamp a score into the [0, 1] interval."""
    return max(0.0, min(1.0, value))


def _light_quality(complexity: str) -> float:
    """Light generic: solid on simple, degrades with complexity."""
    rank = _COMPLEXITY_RANK.get(complexity, _COMPLEXITY_RANK["complex"])
    return _clamp_unit(
        config.QUALITY_LIGHT_BASE - rank * config.QUALITY_LIGHT_COMPLEXITY_PENALTY
    )


def _heavy_quality(model: PoolModel, domain: str) -> float:
    """Heavy tier: specialist bonus only when matched on the intent domain."""
    if model.domain is None:
        return _clamp_unit(config.QUALITY_HEAVY_GENERIC)
    if model.domain == domain:
        return _clamp_unit(config.QUALITY_SPECIALIST_ON_DOMAIN)
    return _clamp_unit(config.QUALITY_SPECIALIST_OFF_DOMAIN)


def expected_quality(model: PoolModel, complexity: str, domain: str) -> float:
    """Estimate the quality ``model`` would yield on this intent, in [0, 1].

    Prototype heuristic (see module docstring), to be recalibrated by the
    LLM-Judge in Phase 5. Does not call the model and has no side effects.

    Args:
        model: Candidate pool model.
        complexity: Estimated complexity label (simple/medium/complex).
        domain: Network domain of the intent (ran/core/security/slice).

    Returns:
        Expected quality clamped to [0, 1].
    """
    if model.tier == "light":
        return _light_quality(complexity)
    return _heavy_quality(model, domain)
