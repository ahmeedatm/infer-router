from __future__ import annotations

import pytest

from app.llm.intent_plan import RerouteOp
from bench.subset import EndpointRef
from bench.verbs import reroute
from bench.verbs.base import VerbError

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_reroute_pins_both_directions_through_the_requested_switch():
    cmds = reroute.to_commands(
        RerouteOp(verb="reroute", src="a", dst="b", via="s3"), EP
    )
    assert len(cmds) == 2
    assert {c.target for c in cmds} == {"s1", "s4"}
    for cmd in cmds:
        assert "priority=150" in cmd.command
        assert "{swport_to:s3}" in cmd.command


def test_reroute_rejects_a_switch_that_is_not_a_path():
    with pytest.raises(VerbError):
        reroute.to_commands(RerouteOp(verb="reroute", src="a", dst="b", via="s9"), EP)


def test_valid_paths_are_the_two_middle_switches():
    assert reroute.VALID_VIA == frozenset({"s2", "s3"})
