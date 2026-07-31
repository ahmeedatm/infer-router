# tests/unit/test_intent_plan.py
from __future__ import annotations

import pytest

from app.llm.intent_plan import (
    BandwidthMaxOp,
    BlockOp,
    IntentPlan,
    IntentPlanError,
    build_plan_prompt,
    parse_plan_response,
)


def test_parses_a_two_operation_plan():
    raw = (
        'Here is the plan: [{"verb": "block", "src": "a", "dst": "b"}, '
        '{"verb": "bandwidth_max", "src": "a", "dst": "c", "bw_mbps": 10}]'
    )
    plan = parse_plan_response("cx-001", raw)
    assert isinstance(plan, IntentPlan)
    assert plan.intent_id == "cx-001"
    assert len(plan.operations) == 2
    assert isinstance(plan.operations[0], BlockOp)
    assert isinstance(plan.operations[1], BandwidthMaxOp)
    assert plan.operations[1].bw_mbps == 10.0


def test_a_bare_object_is_accepted_as_a_single_operation_plan():
    plan = parse_plan_response("s-001", '{"verb": "block", "src": "a", "dst": "b"}')
    assert len(plan.operations) == 1
    assert plan.operations[0].verb == "block"


def test_selector_is_parsed():
    raw = '[{"verb": "block", "src": "a", "dst": "b", "selector": {"proto": "tcp", "port": 22}}]'
    plan = parse_plan_response("s-002", raw)
    assert plan.operations[0].selector is not None
    assert plan.operations[0].selector.port == 22


def test_missing_required_field_is_rejected():
    with pytest.raises(IntentPlanError):
        parse_plan_response("q-001", '[{"verb": "bandwidth_max", "src": "a", "dst": "b"}]')


def test_unknown_verb_is_rejected():
    with pytest.raises(IntentPlanError):
        parse_plan_response("x-001", '[{"verb": "teleport", "src": "a", "dst": "b"}]')


def test_empty_plan_is_rejected():
    with pytest.raises(IntentPlanError):
        parse_plan_response("x-002", "[]")


def test_no_json_at_all_is_rejected():
    with pytest.raises(IntentPlanError):
        parse_plan_response("x-003", "I cannot help with that request.")


def test_plan_is_immutable():
    plan = parse_plan_response("s-003", '[{"verb": "allow", "src": "a", "dst": "b"}]')
    with pytest.raises(Exception):
        plan.operations[0].src = "z"


def test_prompt_lists_endpoints_and_demands_an_array():
    prompt = build_plan_prompt("Isolate a from b", ["a", "b", "probe"])
    assert "a, b, probe" in prompt
    assert "JSON array" in prompt
    for verb in ("allow", "block", "bandwidth_max", "bandwidth_min",
                 "mirror", "reroute", "priority"):
        assert verb in prompt
