"""Pure routing decision for InferRouter-LLM.

This module implements the tri-criteria routing logic. It is a *pure*
function of its inputs: no network call, no Ollama, no API key. Quality
(``q``), cost and latency are assumed already estimated upstream
(complexity estimator, judge, pricing model); this module only decides
which model wins.

Objective (revised 2026-07-22). The router does NOT maximise quality. With a
strong heavy model, quality-maximisation always picks the heavy one and the
routing collapses into always-heavy. Instead the router minimises cost while
guaranteeing a minimum acceptable quality:

    minimise cost   subject to   q(m) >= q_min   and   SLA budgets.

``q_min`` is the operator's quality floor, set per intent from its criticality
(a critical intent demands a higher floor). This is the primal-dual flip of
the earlier "argmax q under budget" formulation, and it matches an operational
SLA: guarantee a quality level, then serve it as cheaply as possible.

Notation:

- SLA admissibility M_sla(e): a candidate ``m`` respects the hard budgets
  ``latency_ms <= l_max`` and ``cost <= c_max`` (inclusive). See
  :func:`admissible`.
- Quality-feasible set: among SLA-admissible candidates, those with
  ``q >= q_min``.
- Objective: among quality-feasible candidates, pick the cheapest (then
  fastest). If none reaches ``q_min`` but the SLA set is non-empty, fall back
  to best-effort (highest ``q`` available) rather than refuse a routable
  intent. See :func:`select`.
- Degenerate case bottom: when M_sla(e) itself is empty, the intent cannot be
  served without violating a hard budget, so :func:`select` returns ``None``.
"""
from __future__ import annotations

from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field


class RouteCandidate(BaseModel):
    """An immutable routing candidate scored along the tri-criteria axes.

    Attributes:
        model_id: Identifier of the candidate model.
        q: Estimated quality in [0, 1].
        cost: Estimated cost, must be >= 0.
        latency_ms: Estimated latency in milliseconds, must be >= 0.
    """

    model_config = ConfigDict(frozen=True)

    model_id: str
    q: float = Field(ge=0.0, le=1.0)
    cost: float = Field(ge=0.0)
    latency_ms: float = Field(ge=0.0)


def admissible(
    candidates: Sequence[RouteCandidate],
    l_max: float,
    c_max: float,
) -> tuple[RouteCandidate, ...]:
    """Compute the hard-SLA admissibility set M_sla(e).

    A candidate is admissible when it respects both SLA budgets:
    ``latency_ms <= l_max`` and ``cost <= c_max`` (inclusive bounds).

    Args:
        candidates: Candidate models, already scored.
        l_max: Maximum tolerated latency (ms) for the intent's SLA.
        c_max: Maximum tolerated cost for the intent's SLA.

    Returns:
        An immutable tuple of admissible candidates, order preserved.
    """
    return tuple(
        c for c in candidates if c.latency_ms <= l_max and c.cost <= c_max
    )


def _cost_key(candidate: RouteCandidate) -> tuple[float, float]:
    """Cost-minimising sort key: cheaper first, then faster."""
    return (candidate.cost, candidate.latency_ms)


def _best_effort_key(candidate: RouteCandidate) -> tuple[float, float, float]:
    """Best-effort key when no candidate reaches q_min: highest q, then
    cheaper, then faster (negations give a min-sortable tuple)."""
    return (-candidate.q, candidate.cost, candidate.latency_ms)


def select(
    candidates: Sequence[RouteCandidate],
    q_min: float,
    l_max: float,
    c_max: float,
) -> Optional[str]:
    """Select the cheapest model guaranteeing ``q >= q_min`` under SLA budgets.

    Steps:
      1. Restrict to the hard-SLA admissible set (see :func:`admissible`).
         If empty, return ``None`` (bottom: unroutable within budget).
      2. Among those, keep candidates with ``q >= q_min``. If any, return the
         cheapest (ties broken by latency).
      3. If none reaches ``q_min``, best-effort: return the highest-quality
         SLA-admissible candidate rather than refuse a routable intent.

    Args:
        candidates: Candidate models, already scored.
        q_min: Minimum acceptable quality (the operator's quality floor).
        l_max: Maximum tolerated latency (ms) for the intent's SLA.
        c_max: Maximum tolerated cost for the intent's SLA.

    Returns:
        The selected ``model_id``, or ``None`` when no candidate satisfies
        the hard SLA budgets.
    """
    feasible = admissible(candidates, l_max, c_max)
    if not feasible:
        return None
    meets_quality = tuple(c for c in feasible if c.q >= q_min)
    if meets_quality:
        return min(meets_quality, key=_cost_key).model_id
    return min(feasible, key=_best_effort_key).model_id
