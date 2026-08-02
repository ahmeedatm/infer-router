"""Bench smoke tests — require a live Mininet (run inside the Lima VM).

Run: sudo python -m pytest tests/integration -m bench -v
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.bench


def test_diamond4_pingall():
    from bench.topology import MininetRunner, build_topology

    net = build_topology("diamond4")
    runner = MininetRunner(net)
    try:
        runner.warmup()
        # h1 and h3 sit on opposite edge switches, so this ping crosses the
        # full diamond over the default path pinned through s2.
        out = runner.ping("h1", "h3")
        assert "0% packet loss" in out
    finally:
        runner.stop()
