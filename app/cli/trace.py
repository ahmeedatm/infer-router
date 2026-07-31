"""Immutable record of what the pipeline did to one intent.

Every stage produces a frozen object; the CLI renderer only reads them. Keeping
the trace separate from both the pipeline and the rendering means the same run
can be printed as text or dumped as JSON without re-running anything.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.llm.schema import Intent, JudgeScore, ModelResponse


class ComplexityStage(BaseModel):
    """What the semantic complexity estimator saw and concluded.

    Attributes:
        label: Predicted class (simple/medium/complex).
        features: Length-independent attributes fed to the classifier.
        elapsed_ms: Wall-clock cost of the estimation itself.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    features: dict[str, float]
    elapsed_ms: float = Field(ge=0.0)


class CandidateView(BaseModel):
    """One pool candidate as the router scored it.

    Attributes:
        model_id: Pool identifier (with domain suffix for a specialist).
        tier: ``light`` or ``heavy``.
        domain: Specialisation domain, ``None`` for a generic model.
        q_expected: Quality the policy expects from it on this intent.
        cost: Expected cost per call (USD).
        latency_ms: Expected latency (ms).
        within_sla: Whether it respects both hard budgets.
        meets_floor: Whether ``q_expected`` reaches the quality floor.
        chosen: Whether the router selected it.
    """

    model_config = ConfigDict(frozen=True)

    model_id: str
    tier: str
    domain: Optional[str]
    q_expected: float = Field(ge=0.0, le=1.0)
    cost: float = Field(ge=0.0)
    latency_ms: float = Field(ge=0.0)
    within_sla: bool
    meets_floor: bool
    chosen: bool


class DecisionStage(BaseModel):
    """The routing arbitration: floor, budgets, candidates, outcome.

    Attributes:
        q_min: Quality floor derived from criticality (or forced by the caller).
        q_min_forced: True when the floor was overridden on the command line.
        l_max: Latency budget (ms).
        c_max: Cost budget (USD per call).
        candidates: Every pool candidate as scored, decision order preserved.
        chosen_model_id: Selected pool id, ``None`` when nothing fits the SLA.
        rationale: Human-readable explanation produced by the router.
        admissible_count: Number of candidates inside the SLA budgets.
    """

    model_config = ConfigDict(frozen=True)

    q_min: float = Field(ge=0.0, le=1.0)
    q_min_forced: bool
    l_max: float
    c_max: float
    candidates: tuple[CandidateView, ...]
    chosen_model_id: Optional[str]
    rationale: str
    admissible_count: int = Field(ge=0)


class ExecutionStage(BaseModel):
    """The real call to the model that won the arbitration.

    Attributes:
        provider: ``api`` or ``local``.
        serving_model_id: Model actually called (may differ from the pool id
            when a local stand-in serves the tier).
        response: Measured response, latency, tokens and cost.
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    serving_model_id: str
    response: ModelResponse


class EvaluationStage(BaseModel):
    """RocketEval scoring of the produced answer.

    Attributes:
        checklist_model: Model that generated the intent-specific criteria.
        judge_model: Local model that graded each criterion.
        score: Per-criterion verdicts and the resulting q.
    """

    model_config = ConfigDict(frozen=True)

    checklist_model: str
    judge_model: str
    score: JudgeScore


class Trace(BaseModel):
    """Everything one CLI run observed, stage by stage."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    complexity: ComplexityStage
    decision: DecisionStage
    execution: Optional[ExecutionStage] = None
    evaluation: Optional[EvaluationStage] = None
