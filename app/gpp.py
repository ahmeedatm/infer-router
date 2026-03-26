"""Gold-Pair Prioritizing (GPP).

Ranks available models by priority p(i) = alpha_i + omega * c / mu_i.
Lower p(i) = higher routing priority.
The gold standard (Accurate-Model) has alpha* = 0 by convention.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelPriority:
    name: str
    url: str
    priority: float
    alpha: float
    mu: float


def compute_priority(alpha_i: float, mu_i: float, c: float, omega: float) -> float:
    """Compute priority p(i) = alpha_i + omega * c / mu_i.

    Lower value = higher routing priority.
    Returns inf if mu_i <= 0 (model unusable or no data yet).
    """
    if mu_i <= 0:
        return float("inf")
    return alpha_i + omega * c / mu_i


def rank_models(
    models: list[tuple[str, str]],
    alphas: dict[str, float],
    mus: dict[str, float],
    c: float,
    omega: float,
) -> list[ModelPriority]:
    """Return models sorted by ascending priority (best = lowest p first).

    Args:
        models: list of (model_name, model_url) tuples
        alphas: inaccuracy per model (1 - accuracy); gold standard has alpha=0
        mus: service rate per model (req/s)
        c: cost coefficient
        omega: calibration weight
    """
    ranked = []
    for name, url in models:
        alpha = alphas.get(name, 0.0)
        mu = mus.get(name, 0.0)
        p = compute_priority(alpha, mu, c, omega)
        ranked.append(ModelPriority(name=name, url=url, priority=p, alpha=alpha, mu=mu))
    return sorted(ranked, key=lambda m: m.priority)
