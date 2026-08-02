"""Runs one intent through the whole InferRouter-LLM pipeline, stage by stage.

Each function here owns exactly one stage and returns a frozen record from
``app.cli.trace``; :func:`run` chains them and stops at the requested stage.
Nothing is printed: rendering lives in ``app.cli.render``.

The stages mirror the system described in the report:
  1. semantic complexity estimation (length-independent attributes),
  2. tri-criteria arbitration (cheapest model above the quality floor),
  3. the real call to the winning model,
  4. RocketEval scoring of the answer by the local judge.
"""
from __future__ import annotations

import time
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.cli import providers
from app.cli.trace import (
    CandidateView,
    ComplexityStage,
    DecisionStage,
    EvaluationStage,
    ExecutionStage,
    Trace,
)
from app.llm.checklist import generate_checklist
from app.llm.features import extract_features
from app.llm.inferrouter import quality_floor, route
from app.llm.judge import judge_rocketeval
from app.llm.policy import expected_quality
from app.llm.pool import PoolModel, default_pool, generic_pool
from app.llm.prompting import build_prompt
from app.llm.router import RouteCandidate, admissible
from app.llm.schema import Intent

Stage = Literal["decision", "execute", "judge"]

# Stages in pipeline order; a run stops as soon as it reaches its target.
STAGE_ORDER: tuple[Stage, ...] = ("decision", "execute", "judge")


class PipelineError(RuntimeError):
    """Raised when a run cannot proceed to the stage it was asked for."""


class RunOptions(BaseModel):
    """Everything a run needs beyond the intent text itself.

    Attributes:
        domain: Network domain of the intent (operator metadata, not inferred).
        criticality: Operator criticality, which sets the quality floor.
        provider: ``api`` (billed) or ``local`` (Ollama, free).
        pool: ``generic`` (only calibrated models) or ``default`` (adds the
            four uncalibrated domain specialists).
        stage: How far to run.
        l_max: Latency budget (ms).
        c_max: Cost budget (USD per call).
        q_min: Explicit quality floor; ``None`` derives it from criticality.
        max_tokens: Generation cap for the target model.
        expected_complexity: Known ground-truth label, when there is one.
    """

    model_config = ConfigDict(frozen=True)

    domain: str = "core"
    criticality: str = "med"
    provider: str = "local"
    pool: str = "generic"
    stage: Stage = "judge"
    l_max: float = Field(default=config.BENCH_L_MAX_MS, ge=0.0)
    c_max: float = Field(default=config.BENCH_C_MAX, ge=0.0)
    q_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int = Field(default=config.RESPONSE_MAX_TOKENS, gt=0)
    expected_complexity: Optional[str] = None


def resolve_pool(name: str) -> tuple[PoolModel, ...]:
    """Return the candidate pool for ``name``.

    Raises:
        PipelineError: on an unknown pool name.
    """
    if name == "generic":
        return generic_pool()
    if name == "default":
        return default_pool()
    raise PipelineError(f"Unknown pool {name!r}; expected 'generic' or 'default'.")


def estimate_complexity(text: str) -> ComplexityStage:
    """Run the persisted estimator on ``text`` and time it.

    The first call also loads the joblib bundle from disk, which costs an order
    of magnitude more than the prediction itself. A warm-up call absorbs that
    load so the reported time is the steady-state cost, the one the report
    measures and the one a deployed router would pay on every intent.

    Raises:
        PipelineError: when the estimator has never been trained/persisted.
    """
    from experiments.train_complexity_estimator import predict_complexity

    try:
        predict_complexity([text])
    except FileNotFoundError as exc:
        raise PipelineError(
            "Complexity estimator not found; train it first with "
            "'python -m experiments.train_complexity_estimator'."
        ) from exc

    start = time.perf_counter()
    label = predict_complexity([text])[0]
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return ComplexityStage(
        label=label, features=dict(extract_features(text)), elapsed_ms=elapsed_ms
    )


def build_intent(text: str, options: RunOptions, complexity: str) -> Intent:
    """Assemble the Intent object the rest of the pipeline consumes.

    ``expected_complexity`` is the dataset annotation field. A command-line
    intent has no annotation, so it falls back to the estimated label unless
    the caller supplies the real one.
    """
    return Intent(
        id="CLI",
        text=text,
        domain=options.domain,
        expected_complexity=options.expected_complexity or complexity,
        criticality=options.criticality,
    )


def _candidate_views(
    models: Sequence[PoolModel],
    complexity: str,
    domain: str,
    floor: float,
    options: RunOptions,
    chosen_id: Optional[str],
) -> tuple[CandidateView, ...]:
    """Score every pool model exactly as the router did, for display."""
    scored = tuple(
        RouteCandidate(
            model_id=model.model_id,
            q=expected_quality(model, complexity, domain),
            cost=model.cost,
            latency_ms=model.latency_ms,
        )
        for model in models
    )
    within = {c.model_id for c in admissible(scored, options.l_max, options.c_max)}
    return tuple(
        CandidateView(
            model_id=model.model_id,
            tier=model.tier,
            domain=model.domain,
            q_expected=candidate.q,
            cost=candidate.cost,
            latency_ms=candidate.latency_ms,
            within_sla=model.model_id in within,
            meets_floor=candidate.q >= floor,
            chosen=model.model_id == chosen_id,
        )
        for model, candidate in zip(models, scored)
    )


def decide(intent: Intent, complexity: str, options: RunOptions) -> DecisionStage:
    """Run the tri-criteria arbitration and record every candidate's score."""
    models = resolve_pool(options.pool)
    floor = options.q_min if options.q_min is not None else quality_floor(
        intent.criticality
    )
    decision = route(
        intent,
        models,
        l_max=options.l_max,
        c_max=options.c_max,
        complexity=complexity,
        q_min=options.q_min,
    )
    return DecisionStage(
        q_min=floor,
        q_min_forced=options.q_min is not None,
        l_max=options.l_max,
        c_max=options.c_max,
        candidates=_candidate_views(
            models, complexity, intent.domain, floor, options, decision.model_id
        ),
        chosen_model_id=decision.model_id,
        rationale=decision.rationale,
        admissible_count=decision.admissible_count,
    )


def execute(
    intent: Intent, decision: DecisionStage, options: RunOptions
) -> ExecutionStage:
    """Call the model that won the arbitration and measure the real response.

    Raises:
        PipelineError: when no candidate satisfied the SLA budgets, so there is
            nothing to call.
    """
    if decision.chosen_model_id is None:
        raise PipelineError(
            "No model satisfies the SLA budgets: nothing to execute. "
            "Raise --l-max or --c-max."
        )
    models = resolve_pool(options.pool)
    chosen = next(m for m in models if m.model_id == decision.chosen_model_id)
    provider = providers.resolve(options.provider)
    serving = providers.serving_model_id(provider, chosen)
    response = providers.call(
        serving, build_prompt(intent), max_tokens=options.max_tokens
    )
    return ExecutionStage(
        provider=provider.name, serving_model_id=serving, response=response
    )


def evaluate(
    intent: Intent, execution: ExecutionStage, options: RunOptions
) -> EvaluationStage:
    """Build the RocketEval checklist and have the local judge grade the answer."""
    provider = providers.resolve(options.provider)
    checklist = generate_checklist(intent, model_id=provider.checklist_model)
    score = judge_rocketeval(intent, execution.response.text, checklist=checklist)
    return EvaluationStage(
        checklist_model=provider.checklist_model,
        judge_model=config.JUDGE_MODEL,
        score=score,
    )


def run(text: str, options: RunOptions) -> Trace:
    """Run ``text`` through the pipeline up to ``options.stage``.

    Args:
        text: Raw intent, as an operator would type it.
        options: Domain, criticality, provider, budgets and target stage.

    Returns:
        An immutable :class:`Trace` holding every stage that ran.

    Raises:
        PipelineError: unknown pool, missing estimator, or nothing routable.
    """
    complexity = estimate_complexity(text)
    intent = build_intent(text, options, complexity.label)
    decision = decide(intent, complexity.label, options)
    if options.stage == "decision":
        return Trace(intent=intent, complexity=complexity, decision=decision)

    execution = execute(intent, decision, options)
    if options.stage == "execute":
        return Trace(
            intent=intent,
            complexity=complexity,
            decision=decision,
            execution=execution,
        )

    evaluation = evaluate(intent, execution, options)
    return Trace(
        intent=intent,
        complexity=complexity,
        decision=decision,
        execution=execution,
        evaluation=evaluation,
    )
