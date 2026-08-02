"""Tests for the terminal rendering of a pipeline trace."""
from __future__ import annotations

from app.cli import render
from app.cli.trace import (
    CandidateView,
    ComplexityStage,
    DecisionStage,
    EvaluationStage,
    ExecutionStage,
    Trace,
)
from app.llm.schema import Intent, JudgeScore, ModelResponse


def _candidate(model_id: str, tier: str, chosen: bool, cost: float) -> CandidateView:
    return CandidateView(
        model_id=model_id,
        tier=tier,
        domain=None,
        q_expected=0.64 if tier == "light" else 0.88,
        cost=cost,
        latency_ms=11000.0,
        within_sla=True,
        meets_floor=tier == "heavy",
        chosen=chosen,
    )


def _decision(chosen_id: str = "heavy-model") -> DecisionStage:
    return DecisionStage(
        q_min=0.5,
        q_min_forced=False,
        l_max=1e9,
        c_max=1e9,
        candidates=(
            _candidate("light-model", "light", chosen_id == "light-model", 0.000168),
            _candidate("heavy-model", "heavy", chosen_id == "heavy-model", 0.0285),
        ),
        chosen_model_id=chosen_id,
        rationale="simple intent, core domain -> heavy generic model",
        admissible_count=2,
    )


def _trace(*, with_execution=False, with_evaluation=False, q=0.67) -> Trace:
    execution = (
        ExecutionStage(
            provider="local",
            serving_model_id="qwen2.5:14b-instruct",
            response=ModelResponse(
                model_id="qwen2.5:14b-instruct",
                text="Use the counter X.\nThen read Y.",
                latency_ms=12345.0,
                prompt_tokens=40,
                completion_tokens=210,
                cost_estimate=0.0,
            ),
        )
        if with_execution
        else None
    )
    evaluation = (
        EvaluationStage(
            checklist_model="qwen2.5:7b-instruct",
            judge_model="gemma2:9b",
            score=JudgeScore(
                q=q, checklist={"Does it avoid inventing values?": True, "Is it correct?": False}
            ),
        )
        if with_evaluation
        else None
    )
    return Trace(
        intent=Intent(
            id="CLI",
            text="Show the PRB utilisation of cell 12.",
            domain="ran",
            expected_complexity="simple",
            criticality="med",
        ),
        complexity=ComplexityStage(
            label="simple", features={"n_entities": 2.0, "n_domains": 1.0}, elapsed_ms=3.4
        ),
        decision=_decision(),
        execution=execution,
        evaluation=evaluation,
    )


def test_intent_section_shows_the_operator_metadata():
    lines = "\n".join(render.render_intent(_trace()))
    assert "métadonnée opérateur" in lines
    assert "ran" in lines


def test_complexity_section_labels_the_attributes_in_plain_words():
    lines = "\n".join(render.render_complexity(_trace()))
    assert "entités (n)=2" in lines
    assert "3.4 ms" in lines


def test_decision_marks_the_chosen_candidate():
    lines = render.render_decision(_decision()).copy()
    chosen_line = next(line for line in lines if "◀ choisi" in line)
    assert "heavy-model" in chosen_line


def test_decision_reports_the_origin_of_the_floor():
    assert any("dérivé de la criticité" in line for line in render.render_decision(_decision()))


def test_forced_floor_is_announced_as_forced():
    decision = _decision().model_copy(update={"q_min_forced": True})
    assert any("forcé en ligne de commande" in line for line in render.render_decision(decision))


def test_unbounded_budgets_are_shown_as_unlimited():
    assert any("illimité" in line for line in render.render_decision(_decision()))


def test_saving_is_computed_against_the_dearest_candidate():
    decision = _decision(chosen_id="light-model")
    assert any("économie" in line and "99 %" in line for line in render.render_decision(decision))


def test_no_saving_line_when_the_dearest_candidate_wins():
    assert not any("économie" in line for line in render.render_decision(_decision()))


def test_execution_section_names_the_pool_model_it_stands_in_for():
    lines = "\n".join(render.render_execution(_trace(with_execution=True)))
    assert "qwen2.5:14b-instruct" in lines
    assert "sert le pool « heavy-model »" in lines


def test_execution_section_is_empty_without_a_call():
    assert render.render_execution(_trace()) == []


def test_evaluation_lists_every_criterion_with_its_verdict():
    lines = "\n".join(render.render_evaluation(_trace(with_execution=True, with_evaluation=True)))
    assert "[oui] Does it avoid inventing values?" in lines
    assert "[NON] Is it correct?" in lines


def test_summary_flags_a_measured_quality_below_the_floor():
    trace = _trace(with_execution=True, with_evaluation=True, q=0.2)
    assert any("PLANCHER MANQUÉ" in line for line in render.render_summary(trace))


def test_summary_confirms_a_measured_quality_above_the_floor():
    trace = _trace(with_execution=True, with_evaluation=True, q=0.9)
    assert any("plancher respecté" in line for line in render.render_summary(trace))


def test_full_render_contains_every_section_header():
    output = render.render(_trace(with_execution=True, with_evaluation=True))
    for title in ("INTENT", "ESTIMATION", "ARBITRAGE", "EXÉCUTION", "ÉVALUATION", "RÉSUMÉ"):
        assert title in output
