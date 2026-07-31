from __future__ import annotations

import pytest

from bench.subset import (
    EndpointRef,
    GroundTruth,
    MirrorSeen,
    PathUsed,
    PingFail,
    PingOk,
    PortBlocked,
    SubsetEntry,
    ThroughputMax,
    ThroughputMin,
    TosMarked,
)
from bench.verifier import (
    Measurements,
    VerifyError,
    decide,
    parse_iperf_mbps,
    parse_ping_loss,
    run_check,
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


# --- run_check: the eight ground-truth checks (Task 10) ---------------------

_OK = "3 packets transmitted, 3 received, 0% packet loss"
_LOST = "3 packets transmitted, 0 received, 100% packet loss"


def _entry(*checks) -> SubsetEntry:
    return SubsetEntry(
        intent_id="t-001", text="t", domain="core", criticality="med",
        expected_complexity="simple", topology="diamond4",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
            "c": EndpointRef(host="h2", mac="00:00:00:00:00:02"),
        },
        checks=checks,
    )


class _FakeRunner:
    def __init__(self, **canned):
        self.canned = canned

    def ping(self, s, d): return self.canned.get("ping", _OK)
    def iperf(self, s, d, port=None, seconds=5): return self.canned.get("iperf", "")
    def iperf_contended(self, s, d, cs, cd, seconds=5): return self.canned.get("iperf", "")
    def tcpdump_count(self, probe_host, seconds=3): return self.canned.get("packets", 0)
    def flow_packets(self, switch, dl_src, dl_dst): return self.canned.get(switch, 0)
    def tos_of(self, s, d): return self.canned.get("tos", 0)


def test_parse_ping_loss_total_loss():
    assert parse_ping_loss(_LOST) == 100.0


def test_parse_ping_loss_rejects_garbage():
    with pytest.raises(VerifyError):
        parse_ping_loss("connect: Network is unreachable")


def test_parse_iperf_mbps_simple_output():
    assert parse_iperf_mbps("[  3]  0.0-5.0 sec  5.0 MBytes  8.39 Mbits/sec") == 8.39


def test_ping_ok_and_ping_fail():
    check_ok = PingOk(check="ping_ok", src="a", dst="b")
    check_fail = PingFail(check="ping_fail", src="a", dst="b")
    assert run_check(check_ok, _entry(check_ok), _FakeRunner(ping=_OK)) is True
    assert run_check(check_fail, _entry(check_fail), _FakeRunner(ping=_OK)) is False
    assert run_check(check_fail, _entry(check_fail), _FakeRunner(ping=_LOST)) is True


def test_throughput_max_allows_15_percent_overshoot():
    check = ThroughputMax(check="throughput_max", src="a", dst="b", max_mbps=8.0)
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(iperf="9.10 Mbits/sec")) is True
    assert run_check(check, entry, _FakeRunner(iperf="9.30 Mbits/sec")) is False


def test_throughput_min_allows_15_percent_undershoot():
    check = ThroughputMin(check="throughput_min", src="a", dst="b", min_mbps=5.0,
                          contender_src="c", contender_dst="b")
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(iperf="4.30 Mbits/sec")) is True
    assert run_check(check, entry, _FakeRunner(iperf="4.10 Mbits/sec")) is False


def test_port_blocked_needs_the_port_dead_and_the_host_alive():
    check = PortBlocked(check="port_blocked", src="a", dst="b", port=22, proto="tcp")
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(iperf="", ping=_OK)) is True
    assert run_check(check, entry, _FakeRunner(iperf="7.0 Mbits/sec", ping=_OK)) is False
    assert run_check(check, entry, _FakeRunner(iperf="", ping=_LOST)) is False


def test_mirror_seen_counts_packets_on_the_probe():
    check = MirrorSeen(check="mirror_seen", src="a", dst="b",
                       probe_host="h4", min_packets=3)
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(packets=5)) is True
    assert run_check(check, entry, _FakeRunner(packets=1)) is False


def test_path_used_requires_traffic_on_one_path_only():
    check = PathUsed(check="path_used", src="a", dst="b", via="s3", not_via="s2")
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(s3=42, s2=0)) is True
    assert run_check(check, entry, _FakeRunner(s3=42, s2=7)) is False
    assert run_check(check, entry, _FakeRunner(s3=0, s2=0)) is False


def test_tos_marked_compares_the_captured_byte():
    check = TosMarked(check="tos_marked", src="a", dst="b", tos=184)
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(tos=184)) is True
    assert run_check(check, entry, _FakeRunner(tos=0)) is False
