from __future__ import annotations

import pytest

from bench.subset import (
    EndpointRef,
    MirrorSeen,
    PathUsed,
    PingFail,
    PingOk,
    PortBlocked,
    PortOpen,
    SubsetEntry,
    ThroughputMax,
    ThroughputMin,
    TosMarked,
)
from bench.verifier import (
    VerifyError,
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


# --- iperf unit prefixes ----------------------------------------------------
# An uncapped intra-switch flow in the VM runs at ~136 Gbits/sec, which iperf
# prints as "Gbits/sec". Accepting only "Mbits/sec" turned every such run into
# "no Mbits/sec field in iperf output", i.e. a bench parse failure charged to
# the model. The unit is part of the measurement, not decoration.

def test_parse_iperf_reads_gigabits():
    assert parse_iperf_mbps(
        "[  1] 0.0000-5.0046 sec  79.3 GBytes   136 Gbits/sec"
    ) == pytest.approx(136_000.0)


def test_parse_iperf_reads_kilobits():
    assert parse_iperf_mbps("[  1] 0.0-5.0 sec  512 KBytes  840 Kbits/sec") == \
        pytest.approx(0.84)


def test_parse_iperf_reads_bare_bits():
    assert parse_iperf_mbps("[  1] 0.0-5.0 sec  40 Bytes  64 bits/sec") == \
        pytest.approx(6.4e-5)


def test_parse_iperf_ignores_the_transfer_column():
    """"GBytes" must not be read as a rate; only the bits/sec field counts."""
    assert parse_iperf_mbps(
        "[  1] 0.0-5.0 sec  79.3 GBytes  9.87 Mbits/sec"
    ) == pytest.approx(9.87)


def test_parse_iperf_error_shows_the_bandwidth_line():
    """A 120-char excerpt stopped inside iperf's banner, so the diagnostic
    never reached the line that would have named the real cause."""
    banner = "-" * 60 + "\nClient connecting to 10.0.0.2, TCP port 5001\n" \
             "TCP window size: 85.3 KByte (default)\n" + "-" * 60 + "\nMARKER"
    with pytest.raises(VerifyError) as excinfo:
        parse_iperf_mbps(banner)
    assert "MARKER" in str(excinfo.value)


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
    def tcpdump_count(self, probe_host, src_host, dst_host, seconds=3, tag="case"):
        self.tcpdump_calls = getattr(self, "tcpdump_calls", []) + [(probe_host, src_host, dst_host)]
        self.tcpdump_tags = getattr(self, "tcpdump_tags", []) + [tag]
        return self.canned.get("packets", 0)
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


def test_mirror_seen_generates_traffic_between_the_checks_own_endpoints():
    """Regression guard: the probed traffic must be the intent's own src/dst,
    not a hardcoded pair, or the measurement is decoupled from the intent."""
    check = MirrorSeen(check="mirror_seen", src="a", dst="b",
                       probe_host="h4", min_packets=3)
    entry = _entry(check)
    runner = _FakeRunner(packets=5)
    run_check(check, entry, runner)
    assert runner.tcpdump_calls == [("h4", "h1", "h3")]


def test_mirror_seen_tags_the_capture_with_the_intent_id():
    """The capture file must be per-case. A fixed path is read back from a
    shared /tmp that survives across cases, so a case whose mirror never
    worked can read a previous case's packets and pass."""
    check = MirrorSeen(check="mirror_seen", src="a", dst="b",
                       probe_host="h4", min_packets=3)
    runner = _FakeRunner(packets=5)
    run_check(check, _entry(check), runner)
    assert runner.tcpdump_tags == ["t-001"]


# --- path_used: generates its own traffic and measures a delta --------------
# The runner's warmup runs before the plan is applied, so the absolute
# counters carry pre-plan traffic from the warmup and from earlier checks of
# the same case. Only the increment caused by traffic generated *after* the
# plan landed says anything about the plan.


class _CountingRunner:
    """Flow counters that only move once traffic has been generated."""

    def __init__(self, before: dict, after: dict):
        self._before, self._after = before, after
        self.pings: list[tuple[str, str]] = []

    def ping(self, src, dst):
        self.pings.append((src, dst))
        return _OK

    def flow_packets(self, switch, dl_src, dl_dst):
        table = self._after if self.pings else self._before
        return table[switch]


_PATH = PathUsed(check="path_used", src="a", dst="b", via="s3", not_via="s2")


def test_path_used_generates_its_own_traffic():
    """Nothing crosses the diamond after the plan is applied unless the check
    sends something itself, so the counters cannot move on their own."""
    runner = _CountingRunner({"s3": 0, "s2": 0}, {"s3": 8, "s2": 0})
    assert run_check(_PATH, _entry(_PATH), runner) is True
    assert runner.pings == [("h1", "h3")]


def test_path_used_ignores_packets_counted_before_the_plan_was_applied():
    """Warmup traffic took the default path through s2. Reading absolute
    counters would see those packets on the wrong path and fail a correct
    reroute; the delta is what the plan is responsible for."""
    runner = _CountingRunner({"s3": 0, "s2": 30}, {"s3": 8, "s2": 30})
    assert run_check(_PATH, _entry(_PATH), runner) is True


def test_path_used_fails_when_the_delta_lands_on_the_excluded_path():
    runner = _CountingRunner({"s3": 0, "s2": 30}, {"s3": 0, "s2": 38})
    assert run_check(_PATH, _entry(_PATH), runner) is False


def test_path_used_fails_when_both_paths_carried_the_new_traffic():
    runner = _CountingRunner({"s3": 0, "s2": 30}, {"s3": 8, "s2": 34})
    assert run_check(_PATH, _entry(_PATH), runner) is False


def test_path_used_raises_when_no_traffic_was_seen_on_either_path():
    """Zero increment on both paths is not "the model routed it wrong" — it is
    "the counters saw nothing", which happens when no flow matching the MAC
    pair exists anywhere. Returning a bare False there reports a model
    failure for a bench condition. The orchestrator catches VerifyError,
    still scores the check false and logs it, so the run continues while the
    condition becomes visible."""
    runner = _CountingRunner({"s3": 5, "s2": 30}, {"s3": 5, "s2": 30})
    with pytest.raises(VerifyError) as excinfo:
        run_check(_PATH, _entry(_PATH), runner)
    message = str(excinfo.value)
    assert "s3" in message and "s2" in message


# --- port_open: the dual of port_blocked ------------------------------------
# ``ping_ok`` alone cannot discriminate, because base connectivity is total by
# default. A permission is only observable as an exception to a denial, so the
# check conjoins both halves the way ``port_blocked`` already does.


_OPEN = PortOpen(check="port_open", src="a", dst="b", port=9100, proto="tcp")


def test_port_open_needs_the_port_alive_and_the_host_isolated():
    assert run_check(_OPEN, _entry(_OPEN),
                     _FakeRunner(iperf="7.0 Mbits/sec", ping=_LOST)) is True


def test_port_open_fails_when_the_broader_denial_never_landed():
    """The state the negative control leaves behind: everything reachable.
    Passing here is exactly the vacuity this check exists to remove."""
    assert run_check(_OPEN, _entry(_OPEN),
                     _FakeRunner(iperf="7.0 Mbits/sec", ping=_OK)) is False


def test_port_open_fails_when_the_exception_was_not_punched_through():
    assert run_check(_OPEN, _entry(_OPEN),
                     _FakeRunner(iperf="", ping=_LOST)) is False


def test_port_open_probes_the_named_port():
    class _Recording(_FakeRunner):
        def iperf(self, s, d, port=None, seconds=5):
            self.port = port
            return "7.0 Mbits/sec"

    runner = _Recording(ping=_LOST)
    run_check(_OPEN, _entry(_OPEN), runner)
    assert runner.port == 9100


def test_tos_marked_compares_the_captured_byte():
    check = TosMarked(check="tos_marked", src="a", dst="b", tos=184)
    entry = _entry(check)
    assert run_check(check, entry, _FakeRunner(tos=184)) is True
    assert run_check(check, entry, _FakeRunner(tos=0)) is False
