"""Expected-quality policy for the tri-criteria router.

At runtime the router does NOT call every model to observe its quality. It
estimates, per candidate, the quality it would *expect* from a policy
heuristic driven by the model profile, the estimated complexity, and the
intent domain. ``router.select`` then picks the best admissible candidate.

This is a prototype heuristic, deliberately coarse. It is meant to be
recalibrated by the local LLM-Judge (offline), which will replace
these hand-set constants with measured quality. The bareme lives in
``app.config`` so it can be tuned without touching this module.

Bareme (all values in [0, 1], from config):
    - Specialist ON the intent domain -> QUALITY_SPECIALIST_ON_DOMAIN (strong,
      flat across complexity: domain expertise carries even hard intents).
    - Heavy generic -> QUALITY_HEAVY_GENERIC (good general quality, flat).
    - Specialist OFF its domain -> QUALITY_SPECIALIST_OFF_DOMAIN (no domain
      bonus, behaves like a heavy generic since it is the same base model).
    - Light generic -> QUALITY_LIGHT_BY_COMPLEXITY[label], the measured
      quality per complexity level (non-linear drop, calibrated 2026-07-22).
"""
from __future__ import annotations

from app import config
from app.llm.pool import PoolModel

def _clamp_unit(value: float) -> float:
    """Clamp a score into the [0, 1] interval."""
    return max(0.0, min(1.0, value))


def _light_quality(complexity: str) -> float:
    """Light generic: measured quality per complexity level.

    Values come directly from the calibration matrix (config
    QUALITY_LIGHT_BY_COMPLEXITY), not a base/penalty model: the real drop is
    non-linear (steep simple->medium, shallow medium->complex). Unknown labels
    fall back to the worst (complex) level.
    """
    table = config.QUALITY_LIGHT_BY_COMPLEXITY
    return _clamp_unit(table.get(complexity, table["complex"]))


def _heavy_quality(model: PoolModel, domain: str) -> float:
    """Heavy tier: a specialist framing helps on its domain and hurts off it.

    Both effects are expressed as deltas on the generic tier rather than as
    absolute levels: the measurement (exp_specialist) yields a reliable gap
    between two arms answering the same intents, while the absolute level
    moves with the intent set. Off-domain is the load-bearing figure, being
    3.6x the on-domain gain: a specialist pool is only worth having if the
    router reliably picks the right domain.
    """
    if model.domain is None:
        return _clamp_unit(config.QUALITY_HEAVY_GENERIC)
    if model.domain == domain:
        return _clamp_unit(config.QUALITY_HEAVY_GENERIC + config.SPECIALIST_ON_DOMAIN_DELTA)
    return _clamp_unit(config.QUALITY_HEAVY_GENERIC + config.SPECIALIST_OFF_DOMAIN_DELTA)


def expected_quality(model: PoolModel, complexity: str, domain: str) -> float:
    """Estimate the quality ``model`` would yield on this intent, in [0, 1].

    Prototype heuristic (see module docstring), to be recalibrated by the
    LLM-Judge. Does not call the model and has no side effects.

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
