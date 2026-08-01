from __future__ import annotations

import pytest

from app.llm.intent_plan import IntentPlan, IntentPlanError
from app.llm.schema import ModelResponse
from bench.subset import EndpointRef, PingFail, SubsetEntry
from experiments.run_realworld_validation import _model_for, plan_for


def _entry() -> SubsetEntry:
    return SubsetEntry(
        intent_id="s-block-001", text="block a from b", domain="security",
        criticality="high", expected_complexity="simple", topology="diamond4",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
        },
        checks=(PingFail(check="ping_fail", src="a", dst="b"),),
    )


def _reply(text: str):
    def _call(model_id, prompt, max_tokens=None):
        _call.prompt = prompt
        return ModelResponse(
            model_id=model_id, text=text, latency_ms=1.0,
            prompt_tokens=1, completion_tokens=1, cost_estimate=0.0,
        )
    return _call


def test_plan_for_parses_the_completion():
    call = _reply('[{"verb": "block", "src": "a", "dst": "b"}]')
    plan = plan_for(_entry(), "light", call)
    assert isinstance(plan, IntentPlan)
    assert plan.operations[0].verb == "block"


def test_prompt_carries_the_intent_endpoints():
    call = _reply('[{"verb": "block", "src": "a", "dst": "b"}]')
    plan_for(_entry(), "light", call)
    assert "a, b" in call.prompt


def test_an_unusable_completion_raises():
    with pytest.raises(IntentPlanError):
        plan_for(_entry(), "light", _reply("I refuse."))


def test_light_and_heavy_pick_the_configured_models():
    from app import config
    assert _model_for(_entry(), "light") == config.MODEL_LIGHT
    assert _model_for(_entry(), "heavy") == config.MODEL_HEAVY


def test_inferrouter_uses_the_annotated_complexity():
    entry = _entry()
    chosen = _model_for(entry, "inferrouter")
    assert isinstance(chosen, str) and chosen
