from __future__ import annotations

import pytest

from app.llm.intent_plan import parse_plan_response
from bench.subset import EndpointRef
from bench.translator import TranslateError, translate_plan
from bench.verbs.base import OvsCommand

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_translates_every_operation_in_order():
    plan = parse_plan_response("cx-001", (
        '[{"verb": "block", "src": "a", "dst": "b"}, '
        '{"verb": "bandwidth_max", "src": "a", "dst": "b", "bw_mbps": 10}]'
    ))
    cmds = translate_plan(plan, EP)
    assert all(isinstance(c, OvsCommand) for c in cmds)
    assert len(cmds) == 3          # 2 drops + 1 policing
    assert "actions=drop" in cmds[0].command
    assert "ingress_policing_rate=10000" in cmds[2].command


def test_a_noop_operation_contributes_nothing():
    plan = parse_plan_response("s-001", '[{"verb": "allow", "src": "a", "dst": "b"}]')
    assert translate_plan(plan, EP) == ()


def test_an_unknown_endpoint_raises_translate_error():
    plan = parse_plan_response("x-001", '[{"verb": "block", "src": "a", "dst": "ghost"}]')
    with pytest.raises(TranslateError):
        translate_plan(plan, EP)


def test_an_invalid_reroute_target_raises_translate_error():
    plan = parse_plan_response("x-002", '[{"verb": "reroute", "src": "a", "dst": "b", "via": "s9"}]')
    with pytest.raises(TranslateError):
        translate_plan(plan, EP)
