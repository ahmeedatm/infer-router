"""Bench smoke tests — require a live ONOS + Mininet (run inside the Lima VM).

Run: sudo python -m pytest tests/integration -m bench -v
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.bench


def test_linear3_pingall_under_onos():
    from bench.topology import MininetRunner, build_topology

    net = build_topology("linear3")
    runner = MininetRunner(net)
    try:
        runner.warmup()
        out = runner.ping("h1", "h3")
        assert "0% packet loss" in out
    finally:
        runner.stop()
