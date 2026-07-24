from __future__ import annotations

import pytest

from bench.subset import GroundTruth
from bench.verifier import (
    Measurements,
    VerifyError,
    decide,
    parse_iperf_mbps,
    parse_ping_loss,
)

PING_OK = "3 packets transmitted, 3 received, 0% packet loss, time 2003ms"
PING_KO = "3 packets transmitted, 0 received, 100% packet loss, time 2049ms"
IPERF = "[  5]  0.0-10.0 sec  11.8 MBytes  9.87 Mbits/sec"


def test_parse_ping_loss():
    assert parse_ping_loss(PING_OK) == 0.0
    assert parse_ping_loss(PING_KO) == 100.0


def test_parse_ping_loss_bad():
    with pytest.raises(VerifyError):
        parse_ping_loss("garbage")


def test_parse_iperf_mbps():
    assert parse_iperf_mbps(IPERF) == pytest.approx(9.87, abs=0.01)


def test_decide_ping_ok():
    gt = GroundTruth(check="ping_ok", src="a", dst="b")
    assert decide(gt, Measurements(loss_pct=0.0)) is True
    assert decide(gt, Measurements(loss_pct=100.0)) is False


def test_decide_ping_fail():
    gt = GroundTruth(check="ping_fail", src="a", dst="b")
    assert decide(gt, Measurements(loss_pct=100.0)) is True
    assert decide(gt, Measurements(loss_pct=0.0)) is False


def test_decide_throughput_min():
    gt = GroundTruth(check="throughput_min", src="a", dst="b", min_mbps=8.0)
    assert decide(gt, Measurements(throughput_mbps=9.87)) is True
    assert decide(gt, Measurements(throughput_mbps=5.0)) is False


def test_decide_throughput_max():
    gt = GroundTruth(check="throughput_max", src="a", dst="b", max_mbps=8.0)
    assert decide(gt, Measurements(throughput_mbps=7.5)) is True
    assert decide(gt, Measurements(throughput_mbps=8.5)) is True  # within 15% tol
    assert decide(gt, Measurements(throughput_mbps=12.0)) is False


def test_decide_throughput_max_requires_cap():
    gt = GroundTruth(check="throughput_max", src="a", dst="b")
    with pytest.raises(VerifyError):
        decide(gt, Measurements(throughput_mbps=5.0))
