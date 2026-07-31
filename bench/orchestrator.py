"""Run one intent/strategy case on the OVS bench (no external controller)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.llm.intent_plan import IntentPlan
from bench.subset import Complexity, SubsetEntry
from bench.translator import TranslateError, translate_plan
from bench.verifier import VerifyError, run_check


class CaseResult(BaseModel):
    """Outcome of one intent under one routing strategy.

    Attributes:
        satisfied: Every ground-truth check held (strict AND). An intent that
            is half realised is not honoured, so this is the headline metric.
        realization_rate: Fraction of checks that held, for diagnosis.
    """

    model_config = ConfigDict(frozen=True)

    intent_id: str
    strategy: str
    expected_complexity: Complexity
    satisfied: bool
    realization_rate: float
    detail: str


def _failed(entry: SubsetEntry, strategy: str, detail: str) -> CaseResult:
    return CaseResult(
        intent_id=entry.intent_id, strategy=strategy,
        expected_complexity=entry.expected_complexity,
        satisfied=False, realization_rate=0.0, detail=detail,
    )


def run_case(
    entry: SubsetEntry,
    plan: Optional[IntentPlan],
    strategy: str,
    runner,
) -> CaseResult:
    """Apply the plan on the data plane, run every check, score the case.

    ``runner`` exposes ``warmup()``, ``apply(commands)`` and the probe methods
    used by :func:`bench.verifier.run_check`. Unit tests inject a fake runner,
    so this stays free of any Mininet dependency.
    """
    if plan is None:
        return _failed(entry, strategy, "LLM produced no valid plan")

    runner.warmup()
    try:
        commands = translate_plan(plan, entry.endpoints)
    except TranslateError as exc:
        return _failed(entry, strategy, f"untranslatable plan: {exc}")

    runner.apply(commands)

    results = []
    for check in entry.checks:
        try:
            results.append(run_check(check, entry, runner))
        except VerifyError as exc:
            results.append(False)
            print(f"{entry.intent_id}/{strategy}: {check.check} unreadable: {exc}")

    rate = sum(results) / len(results)
    verbs = ",".join(op.verb for op in plan.operations)
    return CaseResult(
        intent_id=entry.intent_id, strategy=strategy,
        expected_complexity=entry.expected_complexity,
        satisfied=all(results), realization_rate=rate,
        detail=f"[{verbs}] {sum(results)}/{len(results)} checks",
    )
