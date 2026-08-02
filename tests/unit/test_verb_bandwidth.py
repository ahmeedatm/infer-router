from __future__ import annotations

from app.llm.intent_plan import BandwidthMaxOp, BandwidthMinOp
from bench.subset import EndpointRef
from bench.verbs import bandwidth

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_bandwidth_max_sets_ingress_policing_on_the_source_port():
    cmds = bandwidth.to_commands(
        BandwidthMaxOp(verb="bandwidth_max", src="a", dst="b", bw_mbps=8.0), EP
    )
    assert len(cmds) == 1
    cmd = cmds[0].command
    assert "ingress_policing_rate=8000" in cmd
    assert "ingress_policing_burst=800" in cmd
    assert "{swport:h1}" in cmd


def test_bandwidth_max_burst_never_falls_below_one():
    cmds = bandwidth.to_commands(
        BandwidthMaxOp(verb="bandwidth_max", src="a", dst="b", bw_mbps=0.001), EP
    )
    assert "ingress_policing_burst=1" in cmds[0].command


def test_bandwidth_min_creates_an_htb_queue_and_steers_the_flow():
    cmds = bandwidth.to_commands(
        BandwidthMinOp(verb="bandwidth_min", src="a", dst="b", bw_mbps=5.0), EP
    )
    assert len(cmds) == 2
    qos, flow = cmds
    assert "linux-htb" in qos.command
    assert "min-rate=5000000" in qos.command
    assert "set_queue:1" in flow.command
    # The ordered pair, not the source alone: a floor is granted to one
    # flow, and a dl_src-only match swept every packet the host sent.
    assert "dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:03" in flow.command
    assert "priority=150" in flow.command
