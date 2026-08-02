"""Tests for the CLI pipeline stages (no network, no estimator load)."""
from __future__ import annotations

import pytest

from app import config
from app.cli import pipeline
from app.cli.pipeline import PipelineError, RunOptions
from app.cli.trace import ExecutionStage
from app.llm.schema import Intent, ModelResponse


def _intent(criticality: str = "med", domain: str = "core") -> Intent:
    return Intent(
        id="CLI",
        text="Show the PRB utilisation of cell 12.",
        domain=domain,
        expected_complexity="simple",
        criticality=criticality,
    )


def test_resolve_pool_rejects_an_unknown_name():
    with pytest.raises(PipelineError, match="Unknown pool"):
        pipeline.resolve_pool("everything")


def test_generic_pool_holds_only_the_two_calibrated_tiers():
    assert len(pipeline.resolve_pool("generic")) == 2


def test_build_intent_falls_back_to_the_estimated_label():
    intent = pipeline.build_intent("text", RunOptions(), "complex")
    assert intent.expected_complexity == "complex"


def test_build_intent_prefers_a_supplied_ground_truth():
    options = RunOptions(expected_complexity="simple")
    intent = pipeline.build_intent("text", options, "complex")
    assert intent.expected_complexity == "simple"


def test_decide_sends_a_simple_low_criticality_intent_to_the_light_tier():
    decision = pipeline.decide(_intent("low"), "simple", RunOptions())
    assert decision.chosen_model_id == config.MODEL_LIGHT


def test_decide_sends_a_complex_high_criticality_intent_to_the_heavy_tier():
    decision = pipeline.decide(_intent("high"), "complex", RunOptions())
    assert decision.chosen_model_id == config.MODEL_HEAVY


def test_decide_reports_the_floor_it_derived_from_criticality():
    decision = pipeline.decide(_intent("high"), "simple", RunOptions())
    assert decision.q_min == config.QMIN_BY_CRITICALITY["high"]
    assert decision.q_min_forced is False


def test_decide_marks_a_forced_floor_as_such():
    decision = pipeline.decide(_intent("low"), "simple", RunOptions(q_min=0.9))
    assert decision.q_min == 0.9
    assert decision.q_min_forced is True


def test_decide_scores_every_candidate_and_marks_the_winner():
    decision = pipeline.decide(_intent("low"), "simple", RunOptions())
    assert len(decision.candidates) == 2
    assert sum(1 for c in decision.candidates if c.chosen) == 1


def test_decide_flags_candidates_outside_the_latency_budget():
    options = RunOptions(l_max=12000.0)
    decision = pipeline.decide(_intent("high"), "complex", options)
    heavy = next(c for c in decision.candidates if c.tier == "heavy")
    assert heavy.within_sla is False


def test_execute_refuses_to_call_anything_when_nothing_is_admissible():
    options = RunOptions(l_max=1.0, c_max=1e-9)
    decision = pipeline.decide(_intent(), "simple", options)
    assert decision.chosen_model_id is None
    with pytest.raises(PipelineError, match="No model satisfies"):
        pipeline.execute(_intent(), decision, options)


def test_execute_calls_the_local_stand_in_of_the_chosen_tier(monkeypatch):
    calls: list[str] = []

    def fake_call(model_id, prompt, *, max_tokens=0, client=None):
        calls.append(model_id)
        return ModelResponse(
            model_id=model_id,
            text="answer",
            latency_ms=10.0,
            prompt_tokens=1,
            completion_tokens=2,
            cost_estimate=0.0,
        )

    monkeypatch.setattr(pipeline.providers, "call", fake_call)
    options = RunOptions(provider="local")
    decision = pipeline.decide(_intent("high"), "complex", options)
    stage = pipeline.execute(_intent("high"), decision, options)

    assert calls == [pipeline.providers.LOCAL_HEAVY_MODEL]
    assert stage.serving_model_id == pipeline.providers.LOCAL_HEAVY_MODEL
    assert stage.provider == "local"


def test_evaluate_passes_the_generated_checklist_to_the_judge(monkeypatch):
    seen: dict = {}

    def fake_checklist(intent, *, model_id=None, client=None):
        seen["checklist_model"] = model_id
        return ("Criterion one?", "Criterion two?")

    def fake_judge(intent, text, *, checklist=None, **kwargs):
        seen["checklist"] = checklist
        from app.llm.schema import JudgeScore

        return JudgeScore(q=0.5, checklist={c: i == 0 for i, c in enumerate(checklist)})

    monkeypatch.setattr(pipeline, "generate_checklist", fake_checklist)
    monkeypatch.setattr(pipeline, "judge_rocketeval", fake_judge)

    execution = ExecutionStage(
        provider="local",
        serving_model_id="gemma2:2b",
        response=ModelResponse(
            model_id="gemma2:2b",
            text="answer",
            latency_ms=1.0,
            prompt_tokens=1,
            completion_tokens=1,
            cost_estimate=0.0,
        ),
    )
    stage = pipeline.evaluate(_intent(), execution, RunOptions(provider="local"))

    assert seen["checklist_model"] == pipeline.providers.LOCAL_CHECKLIST_MODEL
    assert seen["checklist"] == ("Criterion one?", "Criterion two?")
    assert stage.judge_model == config.JUDGE_MODEL


def test_run_stops_at_the_decision_stage(monkeypatch):
    from app.cli.trace import ComplexityStage

    monkeypatch.setattr(
        pipeline,
        "estimate_complexity",
        lambda text: ComplexityStage(label="simple", features={}, elapsed_ms=1.0),
    )
    trace = pipeline.run("text", RunOptions(stage="decision", criticality="low"))
    assert trace.execution is None
    assert trace.evaluation is None
    assert trace.decision.chosen_model_id == config.MODEL_LIGHT
