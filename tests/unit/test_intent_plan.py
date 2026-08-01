# tests/unit/test_intent_plan.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.intent_plan import (
    BandwidthMaxOp,
    BlockOp,
    IntentPlan,
    IntentPlanError,
    Selector,
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


def test_stray_bracket_in_preamble_does_not_corrupt_extraction():
    raw = (
        'Note: source is a[edge-node] and dest is b. Here is the plan: '
        '[{"verb": "block", "src": "a", "dst": "b"}]'
    )
    plan = parse_plan_response("t-1", raw)
    assert len(plan.operations) == 1
    assert isinstance(plan.operations[0], BlockOp)


def test_trailing_prose_with_bracket_does_not_corrupt_extraction():
    raw = '[{"verb": "allow", "src": "a", "dst": "b"}] (note: see step [2])'
    plan = parse_plan_response("t-2", raw)
    assert len(plan.operations) == 1
    assert plan.operations[0].verb == "allow"


def test_bracket_inside_json_string_value_is_not_treated_as_structural():
    raw = '[{"verb": "block", "src": "a", "dst": "b[1]"}]'
    plan = parse_plan_response("t-3", raw)
    assert plan.operations[0].src == "a"
    assert plan.operations[0].dst == "b[1]"


def test_escaped_quote_inside_string_does_not_break_extraction():
    raw = '[{"verb": "block", "src": "a\\" ]", "dst": "b"}]'
    plan = parse_plan_response("t-4", raw)
    assert plan.operations[0].src == 'a" ]'


def test_unbalanced_input_is_rejected():
    with pytest.raises(IntentPlanError):
        parse_plan_response("t-5", '[{"verb": "block", "src": "a", "dst": "b"')


def test_array_wins_over_earlier_bare_object():
    raw = (
        '{"verb": "block", "src": "x", "dst": "y"} then the real plan is: '
        '[{"verb": "allow", "src": "a", "dst": "b"}]'
    )
    plan = parse_plan_response("t-6", raw)
    assert len(plan.operations) == 1
    assert plan.operations[0].verb == "allow"
    assert plan.operations[0].src == "a"


def test_incidental_bracketed_list_before_the_real_plan_is_skipped():
    raw = (
        'using ports [80, 443], here is the plan: '
        '[{"verb": "block", "src": "a", "dst": "b"}]'
    )
    plan = parse_plan_response("t-7", raw)
    assert len(plan.operations) == 1
    assert isinstance(plan.operations[0], BlockOp)


def test_incidental_object_before_the_real_plan_is_skipped():
    raw = 'context {"site": "A"} then [{"verb": "allow", "src": "a", "dst": "b"}]'
    plan = parse_plan_response("t-8", raw)
    assert len(plan.operations) == 1
    assert plan.operations[0].verb == "allow"


def test_genuinely_invalid_plan_reports_the_schema_problem():
    with pytest.raises(IntentPlanError, match="bw_mbps"):
        parse_plan_response("t-9", '[{"verb": "bandwidth_max", "src": "a", "dst": "b"}]')


def test_several_incidental_fragments_and_no_valid_plan_still_rejected():
    raw = (
        'ports [80, 443] and metadata {"site": "A", "region": "eu"} '
        'nothing usable here'
    )
    with pytest.raises(IntentPlanError):
        parse_plan_response("t-10", raw)


# --- Selector: a port match needs a transport protocol ----------------------


def test_selector_accepts_a_port_with_a_transport_proto():
    assert Selector(proto="tcp", port=22).port == 22
    assert Selector(proto="udp", port=53).port == 53


def test_selector_accepts_a_proto_without_a_port():
    assert Selector(proto="icmp").port is None


def test_selector_rejects_a_port_without_a_proto():
    """``{"port": 22}`` alone translates to ``dl_type=0x0800,tp_dst=22``,
    which ovs-ofctl rejects for missing prerequisites. The rule is therefore
    never installed: scoring it as a realised operation charges the model for
    an outcome the bench could not produce."""
    with pytest.raises(ValidationError):
        Selector(port=22)


def test_selector_rejects_a_port_with_icmp():
    """``nw_proto=1,tp_dst=22`` is rejected the same way: ICMP has no ports."""
    with pytest.raises(ValidationError):
        Selector(proto="icmp", port=22)


def test_a_plan_with_a_portless_proto_selector_fails_to_parse():
    """The rejection must surface as an IntentPlanError, so an unrealisable
    operation is measured as a model failure rather than silently applied."""
    raw = '[{"verb": "block", "src": "a", "dst": "b", "selector": {"port": 22}}]'
    with pytest.raises(IntentPlanError):
        parse_plan_response("s-003", raw)


def test_prompt_states_that_a_port_requires_tcp_or_udp():
    """A model emitting a bare port is a plausible completion unless the
    schema says otherwise, so the constraint belongs in the prompt too."""
    prompt = build_plan_prompt("Deny SSH from a to b", ["a", "b"])
    assert "port" in prompt
    assert 'requires "proto"' in prompt


# --- a chosen array is the model's answer: all of it, or nothing -----------


def test_one_invalid_operation_rejects_the_whole_array():
    """An array is the model's answer. If one operation is unusable, the
    answer is unusable: that is a measured model failure. Falling through to
    the bare-object branch instead returned the first standalone object that
    validated, silently truncating a four-operation plan to one and scoring
    it as a partial success — worse than either honest outcome, and biased
    against multi-operation (complex) intents."""
    raw = ('[{"verb": "block", "src": "a", "dst": "b", '
           '"selector": {"port": 22}}, '
           '{"verb": "bandwidth_max", "src": "a", "dst": "b", "bw_mbps": 8}]')
    with pytest.raises(IntentPlanError):
        parse_plan_response("c-004", raw)


def test_a_bad_selector_mid_array_names_the_operation_and_the_problem():
    raw = ('[{"verb": "allow", "src": "a", "dst": "b"}, '
           '{"verb": "block", "src": "a", "dst": "b", "selector": {"port": 22}}, '
           '{"verb": "bandwidth_max", "src": "a", "dst": "b", "bw_mbps": 8}]')
    with pytest.raises(IntentPlanError) as excinfo:
        parse_plan_response("c-004", raw)
    message = str(excinfo.value)
    assert "1" in message, "the failing operation's index must be named"
    assert "proto" in message, "the selector problem must be described"


def test_an_unknown_verb_mid_array_rejects_the_whole_array():
    raw = ('[{"verb": "teleport", "src": "a", "dst": "b"}, '
           '{"verb": "block", "src": "a", "dst": "b"}]')
    with pytest.raises(IntentPlanError) as excinfo:
        parse_plan_response("c-004", raw)
    assert "teleport" in str(excinfo.value)


def test_incidental_json_before_a_valid_array_still_yields_the_full_array():
    """Candidate selection is unchanged: only a *chosen* array's schema
    failure became terminal."""
    raw = ('ports [80, 443] and context {"site": "A"}, plan: '
           '[{"verb": "allow", "src": "a", "dst": "b"}, '
           '{"verb": "bandwidth_max", "src": "a", "dst": "b", "bw_mbps": 8}]')
    plan = parse_plan_response("t-11", raw)
    assert [op.verb for op in plan.operations] == ["allow", "bandwidth_max"]


def test_a_lone_bare_object_is_still_a_one_operation_plan():
    """The bare-object branch survives for the case it was built for: a
    completion holding no array at all."""
    raw = 'Here is what I would do: {"verb": "block", "src": "a", "dst": "b"}'
    plan = parse_plan_response("t-12", raw)
    assert len(plan.operations) == 1
    assert plan.operations[0].verb == "block"


def test_a_four_operation_array_is_returned_whole():
    """Nothing truncates on the happy path."""
    raw = ('[{"verb": "allow", "src": "a", "dst": "b"}, '
           '{"verb": "block", "src": "a", "dst": "c"}, '
           '{"verb": "bandwidth_max", "src": "a", "dst": "b", "bw_mbps": 8}, '
           '{"verb": "mirror", "src": "a", "dst": "b", "to": "probe"}]')
    plan = parse_plan_response("c-001", raw)
    assert [op.verb for op in plan.operations] == [
        "allow", "block", "bandwidth_max", "mirror",
    ]
