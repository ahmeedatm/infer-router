from __future__ import annotations

from app.llm.intent_plan import AllowOp, BlockOp, Selector
from bench.subset import EndpointRef
from bench.verbs import allow_block

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_allow_without_selector_is_a_noop():
    assert allow_block.to_commands(AllowOp(verb="allow", src="a", dst="b"), EP) == ()


def test_block_drops_both_directions_on_every_switch():
    cmds = allow_block.to_commands(BlockOp(verb="block", src="a", dst="b"), EP)
    assert len(cmds) == 2
    assert all(c.target == "all" for c in cmds)
    assert "dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:03" in cmds[0].command
    assert "dl_src=00:00:00:00:00:03,dl_dst=00:00:00:00:00:01" in cmds[1].command
    assert all("priority=200" in c.command and "actions=drop" in c.command
               for c in cmds)


def test_block_with_l4_selector_uses_priority_300_and_matches_the_port():
    op = BlockOp(verb="block", src="a", dst="b",
                 selector=Selector(proto="tcp", port=22))
    cmds = allow_block.to_commands(op, EP)
    assert len(cmds) == 1
    cmd = cmds[0].command
    assert "priority=300" in cmd
    assert "dl_type=0x0800" in cmd
    assert "nw_proto=6" in cmd
    assert "tp_dst=22" in cmd
    assert "actions=drop" in cmd


def test_allow_with_selector_punches_a_hole_at_priority_300():
    """Both directions, or the hole is not a hole: the request passes at 300
    and the response falls back into the broader drop at 200."""
    op = AllowOp(verb="allow", src="a", dst="b",
                 selector=Selector(proto="udp", port=53))
    cmds = allow_block.to_commands(op, EP)
    assert len(cmds) == 2
    assert all("priority=300" in c.command for c in cmds)
    assert all("nw_proto=17" in c.command for c in cmds)
    assert all("actions=normal" in c.command for c in cmds)
    assert "tp_dst=53" in cmds[0].command
    assert "tp_src=53" in cmds[1].command
