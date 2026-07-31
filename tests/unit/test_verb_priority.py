from __future__ import annotations

from app.llm.intent_plan import PriorityOp
from bench.subset import EndpointRef
from bench.verbs import priority

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_high_priority_marks_ef():
    cmds = priority.to_commands(
        PriorityOp(verb="priority", src="a", dst="b", klass="high"), EP
    )
    assert len(cmds) == 1
    cmd = cmds[0].command
    assert "mod_nw_tos:184" in cmd
    assert "priority=150" in cmd
    assert "dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:03" in cmd


def test_low_priority_marks_cs1():
    cmds = priority.to_commands(
        PriorityOp(verb="priority", src="a", dst="b", klass="low"), EP
    )
    assert "mod_nw_tos:32" in cmds[0].command


def test_class_to_tos_mapping_is_exposed():
    assert priority.TOS_BY_CLASS == {"high": 184, "normal": 0, "low": 32}
