from __future__ import annotations

import json

import pytest

from app.llm.intent_plan import IntentPlan, IntentPlanError
from app.llm.schema import ModelResponse
from bench.subset import EndpointRef, PingFail, SubsetEntry
from bench.translator import translate_plan
from experiments.run_realworld_validation import (
    NOOP_STRATEGY,
    _model_for,
    _STRATEGIES,
    main,
    plan_for,
)

_TWO_ENTRY_SUBSET_YAML = """
- intent_id: e1
  text: block a from b
  domain: security
  criticality: high
  expected_complexity: simple
  topology: diamond4
  endpoints:
    a: {host: h1, mac: "00:00:00:00:00:01"}
    b: {host: h3, mac: "00:00:00:00:00:03"}
  checks:
    - {check: ping_fail, src: a, dst: b}
- intent_id: e2
  text: allow a to b
  domain: security
  criticality: low
  expected_complexity: simple
  topology: diamond4
  endpoints:
    a: {host: h1, mac: "00:00:00:00:00:01"}
    b: {host: h3, mac: "00:00:00:00:00:03"}
  checks:
    - {check: ping_ok, src: a, dst: b}
"""


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
    assert plan.intent_id == "s-block-001"
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


def test_inferrouter_resolves_to_a_pool_model():
    """The ``inferrouter`` strategy must produce *some* model id.

    This does NOT verify that the subset's ``expected_complexity`` drives the
    choice: ``route()`` (app/llm/inferrouter.py) never reads
    ``intent.expected_complexity``. It estimates complexity from
    ``intent.text`` itself, because in production nobody knows an intent's
    true complexity ahead of time — that annotation must never drive
    routing. The subset's label is carried on the ``Intent`` object purely
    for the results/reporting axis (comparing strategies against the
    intent's known difficulty), not as routing input.
    """
    entry = _entry()
    chosen = _model_for(entry, "inferrouter")
    assert isinstance(chosen, str) and chosen


def test_main_records_a_failure_and_keeps_processing(tmp_path):
    """The task's central contract: an unusable completion for one
    (entry, strategy) pair is recorded as ``{"failed": true, ...}`` and does
    NOT abort the run — the other strategies for that same intent, and every
    later entry, must still be processed and written to disk. A dropped
    intent would silently shrink phase B's denominator instead of being
    measured as a failure.
    """
    subset_path = tmp_path / "subset.yaml"
    subset_path.write_text(_TWO_ENTRY_SUBSET_YAML)
    results_dir = tmp_path / "results"

    call_count = {"n": 0}

    def fake_call(model_id, prompt, max_tokens=None):
        call_count["n"] += 1
        # Iteration order is deterministic: e1/light, e1/heavy,
        # e1/inferrouter, e2/light, e2/heavy, e2/inferrouter. Fail exactly
        # the 2nd call (e1/heavy) so both "other strategies of the same
        # intent" and "later entries" are exercised by the remaining calls.
        if call_count["n"] == 2:
            text = "I refuse."
        else:
            text = '[{"verb": "block", "src": "a", "dst": "b"}]'
        return ModelResponse(
            model_id=model_id, text=text, latency_ms=1.0,
            prompt_tokens=1, completion_tokens=1, cost_estimate=0.0,
        )

    exit_code = main(
        ["--subset", str(subset_path)], call=fake_call, results_dir=results_dir
    )
    assert exit_code == 0

    failure = json.loads((results_dir / "heavy" / "e1.json").read_text())
    assert failure["failed"] is True
    assert failure["reason"]

    # e1's other strategies were not skipped because heavy failed.
    assert (results_dir / "light" / "e1.json").exists()
    assert (results_dir / "inferrouter" / "e1.json").exists()

    # e2 (the later entry) was still fully processed for every strategy.
    assert (results_dir / "light" / "e2.json").exists()
    assert (results_dir / "heavy" / "e2.json").exists()
    assert (results_dir / "inferrouter" / "e2.json").exists()


# --- the noop negative control ----------------------------------------------


def _forbidden_call(model_id, prompt, max_tokens=None):
    raise AssertionError(f"the noop control called the API: {model_id}")


def test_noop_produces_a_valid_plan_without_calling_any_model():
    plan = plan_for(_entry(), NOOP_STRATEGY, _forbidden_call)
    assert isinstance(plan, IntentPlan)
    assert plan.intent_id == "s-block-001"


def test_noop_translates_to_zero_ovs_commands():
    """The control's whole point: it parses and applies, yet leaves the data
    plane exactly as build_topology left it. Any check still passing under
    it is a check no model can influence."""
    entry = _entry()
    plan = plan_for(entry, NOOP_STRATEGY, _forbidden_call)
    assert translate_plan(plan, entry.endpoints) == ()


def test_noop_uses_the_intents_own_endpoints():
    """A plan naming an endpoint outside the entry would be untranslatable
    and would score 0 for the wrong reason."""
    entry = _entry()
    plan = plan_for(entry, NOOP_STRATEGY, _forbidden_call)
    for op in plan.operations:
        assert op.src in entry.endpoints
        assert op.dst in entry.endpoints


def test_noop_has_no_model_and_cannot_resolve_one():
    """Belt and braces on the money guarantee: even the model-resolution path
    refuses the control strategy."""
    with pytest.raises(ValueError):
        _model_for(_entry(), NOOP_STRATEGY)


def test_noop_is_part_of_the_default_strategy_sweep():
    assert NOOP_STRATEGY in _STRATEGIES


def test_main_runs_the_noop_control_without_spending_anything(tmp_path):
    subset_path = tmp_path / "subset.yaml"
    subset_path.write_text(_TWO_ENTRY_SUBSET_YAML)
    results_dir = tmp_path / "results"

    exit_code = main(
        ["--subset", str(subset_path), "--strategy", NOOP_STRATEGY],
        call=_forbidden_call, results_dir=results_dir,
    )
    assert exit_code == 0
    for intent_id in ("e1", "e2"):
        payload = json.loads((results_dir / NOOP_STRATEGY / f"{intent_id}.json").read_text())
        assert payload["operations"]
        assert "failed" not in payload
