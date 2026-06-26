"""Pure routing decision for InferRouter-LLM.

This module implements the tri-criteria routing logic. It is a *pure*
function of its inputs: no network call, no Ollama, no API key. Quality
(``q``), cost and latency are assumed already estimated upstream
(complexity estimator, judge, pricing model); this module only decides
which model wins.

Notation:

- Admissibility set M(e): a candidate ``m`` is admissible for an intent
  ``e`` when ``latency_ms <= l_max`` and ``cost <= c_max``. Both bounds
  are SLA budgets and the comparison is inclusive. See :func:`admissible`.
- Objective R*(e) = argmax_{m in M(e)} q(m): among admissible candidates,
  pick the one of highest estimated quality. See :func:`select`.
- Degenerate case ⊥: when M(e) is empty, the intent is not routable
  without violating an SLA, so :func:`select` returns ``None`` rather than
  forcing a non-compliant choice.
- Pareto tie-break: ties on ``q`` are resolved lexicographically by cost
  ascending, then latency ascending (cheaper and faster preferred).
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
    """Compute the admissibility set M(e).

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


def _tie_break_key(candidate: RouteCandidate) -> tuple[float, float, float]:
    """Sort key implementing the objective and Pareto tie-break.

    Highest ``q`` wins (negated for ascending sort), then cost ascending,
    then latency ascending. The minimum under this key is R*(e).
    """
    return (-candidate.q, candidate.cost, candidate.latency_ms)


def select(
    candidates: Sequence[RouteCandidate],
    l_max: float,
    c_max: float,
) -> Optional[str]:
    """Select R*(e) = argmax_{m in M(e)} q, or ⊥ when M(e) is empty.

    Restricts the candidates to the admissibility set M(e) (see
    :func:`admissible`), then picks the highest-quality candidate. Ties on
    ``q`` are broken by cost then latency (Pareto criterion).

    Args:
        candidates: Candidate models, already scored.
        l_max: Maximum tolerated latency (ms) for the intent's SLA.
        c_max: Maximum tolerated cost for the intent's SLA.

    Returns:
        The selected ``model_id``, or ``None`` for the degenerate case ⊥
        where no candidate satisfies the SLA budgets.
    """
    feasible = admissible(candidates, l_max, c_max)
    if not feasible:
        return None
    return min(feasible, key=_tie_break_key).model_id
