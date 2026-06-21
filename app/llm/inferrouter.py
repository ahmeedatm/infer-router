"""Tri-criteria routing orchestrator (Phase 3, pure decision).

Wires the existing building blocks into a single decision:
    complexity estimate + domain -> expected quality per candidate
    -> admissibility + argmax-q (router.select) -> chosen model.

No network and no Ollama call: the decision is a pure function of the intent,
the pool, the SLA budgets and the complexity label. The complexity estimator
is imported lazily and only when ``complexity`` is not supplied, so pure unit
tests that pass it explicitly never load sklearn.
"""
from __future__ import annotations

from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.llm.policy import expected_quality
from app.llm.pool import PoolModel, default_pool
from app.llm.router import RouteCandidate, admissible, select
from app.llm.schema import Intent


class RouteDecision(BaseModel):
    """Immutable outcome of a routing decision.

    Attributes:
        model_id: Chosen model id, or ``None`` for the degenerate case where
            no candidate satisfies the SLA budgets.
        complexity: Complexity label used for the decision.
        rationale: Human-readable explanation of the decision.
        admissible_count: Number of candidates within the SLA budgets.
    """

    model_config = ConfigDict(frozen=True)

    model_id: Optional[str]
    complexity: str
    rationale: str
    admissible_count: int = Field(ge=0)


def _estimate_complexity(text: str) -> str:
    """Estimate complexity from raw text (lazy import to avoid sklearn cost)."""
    from experiments.train_complexity_estimator import predict_complexity

    return predict_complexity([text])[0]


def _to_candidate(model: PoolModel, complexity: str, domain: str) -> RouteCandidate:
    """Score a pool model into a RouteCandidate via the expected-quality policy."""
    return RouteCandidate(
        model_id=model.model_id,
        q=expected_quality(model, complexity, domain),
        cost=model.cost,
        latency_ms=model.latency_ms,
    )


def _rationale(
    chosen: Optional[PoolModel], complexity: str, domain: str
) -> str:
    """Build a coherent, traceable explanation of the decision."""
    if chosen is None:
        return (
            f"{complexity} intent, {domain} domain -> no admissible model "
            f"within SLA budgets"
        )
    if chosen.domain == domain:
        target = f"specialized {domain} model"
    elif chosen.tier == "heavy":
        target = "heavy generic model"
    else:
        target = "light generic model"
    return f"{complexity} intent, {domain} domain -> {target} ({chosen.model_id})"


def route(
    intent: Intent,
    pool: Optional[Sequence[PoolModel]] = None,
    *,
    l_max: float,
    c_max: float,
    complexity: Optional[str] = None,
) -> RouteDecision:
    """Decide which model should serve ``intent`` under SLA budgets.

    Args:
        intent: The network intent to route.
        pool: Candidate models; defaults to :func:`pool.default_pool`.
        l_max: Maximum tolerated latency (ms) for the intent SLA.
        c_max: Maximum tolerated cost for the intent SLA.
        complexity: Pre-estimated complexity label. When omitted, it is
            estimated from ``intent.text`` (loads the persisted model lazily).

    Returns:
        An immutable :class:`RouteDecision`. ``model_id`` is ``None`` in the
        degenerate case where no candidate is admissible.
    """
    models = tuple(pool) if pool is not None else default_pool()
    label = complexity if complexity is not None else _estimate_complexity(intent.text)
    domain = intent.domain

    candidates = tuple(_to_candidate(m, label, domain) for m in models)
    feasible = admissible(candidates, l_max, c_max)
    chosen_id = select(candidates, l_max, c_max)
    chosen = next((m for m in models if m.model_id == chosen_id), None)

    return RouteDecision(
        model_id=chosen_id,
        complexity=label,
        rationale=_rationale(chosen, label, domain),
        admissible_count=len(feasible),
    )
