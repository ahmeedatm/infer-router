from __future__ import annotations

from app.llm.schema import ModelResponse
from bench.subset import EndpointRef, GroundTruth, SubsetEntry
from experiments.run_realworld_validation import action_for


def _entry() -> SubsetEntry:
    return SubsetEntry(
        intent_id="sec-001", text="Block a from b", domain="security",
        criticality="high", klass="isolation", topology="linear3",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
        },
        ground_truth=GroundTruth(check="ping_fail", src="a", dst="b"),
    )


def test_action_for_uses_injected_call():
    def fake_call(model_id, prompt, **kw):
        assert "a" in prompt and "b" in prompt
        return ModelResponse(
            model_id=model_id, text='{"action":"block","src":"a","dst":"b"}',
            latency_ms=1.0, prompt_tokens=1, completion_tokens=1, cost_estimate=0.0,
        )

    action = action_for(_entry(), "heavy", call=fake_call)
    assert action.action == "block" and action.intent_id == "sec-001"
