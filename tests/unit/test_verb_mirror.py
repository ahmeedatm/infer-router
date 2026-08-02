from __future__ import annotations

import pytest

from app.llm.intent_plan import MirrorOp
from bench.subset import EndpointRef
from bench.verbs import mirror
from bench.verbs.base import VerbError

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
    "probe": EndpointRef(host="h4", mac="00:00:00:00:00:04"),
}


def test_mirror_spans_the_source_port_to_the_probe_port():
    cmds = mirror.to_commands(
        MirrorOp(verb="mirror", src="a", dst="b", to="probe"), EP
    )
    assert len(cmds) == 1
    cmd = cmds[0].command
    assert "create mirror" in cmd
    assert "select-src-port=@srcport" in cmd
    assert "output-port=@outport" in cmd
    assert "{swport:h1}" in cmd
    assert "{swport:h4}" in cmd


def test_mirror_rejects_an_unknown_probe():
    with pytest.raises(VerbError):
        mirror.to_commands(MirrorOp(verb="mirror", src="a", dst="b", to="ghost"), EP)
