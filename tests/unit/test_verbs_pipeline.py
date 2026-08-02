"""The pipeline invariant: two verbs acting on one flow must compose.

c-003 asks for the same flow to be rerouted and marked. With every verb
installing at priority 150 in one table, a packet matched exactly one of the
two rules and OVS chose which, so ``path_used`` and ``tos_marked`` could not
both hold. The fix is structural rather than a priority tweak: each concern
gets its own table and hands the packet on with ``resubmit``.

These tests pin that structure at the level where it is decided, in the verb
modules, so a regression fails on the Mac in a second instead of in a Mininet
sweep. Nothing here imports Mininet.
"""
from __future__ import annotations

import re

from app.llm.intent_plan import (
    BandwidthMinOp,
    BlockOp,
    PriorityOp,
    RerouteOp,
    Selector,
)
from bench.subset import EndpointRef
from bench.verbs import allow_block, bandwidth, priority, reroute
from bench.verbs.base import TABLE_FORWARD, TABLE_MARK, TABLE_QUEUE

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}

_TABLE_RE = re.compile(r"table=(\d+)")


def _tables(commands) -> set[int]:
    return {
        int(m.group(1))
        for c in commands
        for m in [_TABLE_RE.search(c.command)]
        if m is not None
    }


def test_the_stages_are_three_distinct_tables():
    assert len({TABLE_MARK, TABLE_QUEUE, TABLE_FORWARD}) == 3
    assert TABLE_MARK < TABLE_QUEUE < TABLE_FORWARD


def test_marking_happens_upstream_of_forwarding_and_resubmits():
    cmds = priority.to_commands(
        PriorityOp(verb="priority", src="a", dst="b", klass="high"), EP
    )
    assert _tables(cmds) == {TABLE_MARK}
    # Handing the packet on is the whole point: an action list ending in
    # ``normal`` or ``output`` would consume the packet and the forwarding
    # stage would never run, which is the collision in another costume.
    assert f"resubmit(,{TABLE_QUEUE})" in cmds[0].command


def test_queueing_happens_upstream_of_forwarding_and_resubmits():
    cmds = bandwidth.to_commands(
        BandwidthMinOp(verb="bandwidth_min", src="a", dst="b", bw_mbps=5.0), EP
    )
    flow = [c for c in cmds if "add-flow" in c.command]
    assert _tables(flow) == {TABLE_QUEUE}
    assert f"resubmit(,{TABLE_FORWARD})" in flow[0].command


def test_reroute_and_block_decide_in_the_forwarding_table():
    routed = reroute.to_commands(
        RerouteOp(verb="reroute", src="a", dst="b", via="s3"), EP
    )
    dropped = allow_block.to_commands(
        BlockOp(verb="block", src="a", dst="b"), EP
    )
    narrowed = allow_block.to_commands(
        BlockOp(verb="block", src="a", dst="b",
                selector=Selector(proto="tcp", port=22)), EP
    )
    assert _tables(routed) == {TABLE_FORWARD}
    assert _tables(dropped) == {TABLE_FORWARD}
    assert _tables(narrowed) == {TABLE_FORWARD}


def test_marking_and_rerouting_the_same_flow_do_not_collide():
    """The c-003 regression, stated as a property rather than a sweep result.

    Two rules may share a priority as long as they sit in different tables:
    the packet visits both. They must never share a table, whatever the
    priorities, because then only one of them applies.
    """
    marked = priority.to_commands(
        PriorityOp(verb="priority", src="a", dst="b", klass="high"), EP
    )
    routed = reroute.to_commands(
        RerouteOp(verb="reroute", src="a", dst="b", via="s3"), EP
    )
    assert _tables(marked).isdisjoint(_tables(routed))
