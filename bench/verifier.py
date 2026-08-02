"""Data-plane verification: run one ground-truth check against the network.

:func:`run_check` drives a check straight from ``entry.checks`` through the
runner protocol and decides in one step. Each check derives from the
intent's ground truth, never from the plan the model produced.
"""
from __future__ import annotations

import re

from bench.subset import (
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

_LOSS_RE = re.compile(r"([\d.]+)%\s*packet loss")

# iperf scales the unit to the measurement: an uncapped intra-switch flow in
# the VM reads "136 Gbits/sec", a policed one "8.2 Mbits/sec", a starved one
# "840 Kbits/sec". Matching "Mbits/sec" alone silently rejected every run
# outside one decade and reported it as an unparseable output, which charged
# a bench limitation to the model.
_IPERF_RE = re.compile(r"([\d.]+)\s*([KMG]?)bits/sec")

_MBPS_PER_UNIT = {"": 1e-6, "K": 1e-3, "M": 1.0, "G": 1e3}

# Enough of the output to reach iperf's bandwidth line. A shorter excerpt
# stopped inside the connection banner, so the diagnostic never showed the
# field it was complaining about.
_EXCERPT = 300

# Policing and measurement overshoot the cap slightly; htb floors undershoot.
THROUGHPUT_TOLERANCE = 1.15
FLOOR_TOLERANCE = 0.85


class VerifyError(ValueError):
    """Raised when a command output cannot be parsed."""


def parse_ping_loss(output: str) -> float:
    m = _LOSS_RE.search(output)
    if m is None:
        raise VerifyError(f"no packet-loss field in ping output: {output[:120]!r}")
    return float(m.group(1))


def parse_iperf_mbps(output: str) -> float:
    """Read iperf's bandwidth field, whatever decade it chose to print it in."""
    m = _IPERF_RE.search(output)
    if m is None:
        raise VerifyError(
            f"no bits/sec field in iperf output: {output[:_EXCERPT]!r}"
        )
    return float(m.group(1)) * _MBPS_PER_UNIT[m.group(2)]


def _host(entry: SubsetEntry, key: str) -> str:
    return entry.endpoints[key].host


def _throughput_or_zero(output: str) -> float:
    """A refused connection yields no Mbits/sec line, which reads as 0."""
    try:
        return parse_iperf_mbps(output)
    except VerifyError:
        return 0.0


def run_check(check, entry: SubsetEntry, runner) -> bool:
    """Probe the data plane and decide whether this check holds."""
    src, dst = _host(entry, check.src), _host(entry, check.dst)

    if isinstance(check, PingOk):
        return parse_ping_loss(runner.ping(src, dst)) < 100.0

    if isinstance(check, PingFail):
        return parse_ping_loss(runner.ping(src, dst)) >= 100.0

    if isinstance(check, ThroughputMax):
        measured = parse_iperf_mbps(runner.iperf(src, dst))
        return measured <= check.max_mbps * THROUGHPUT_TOLERANCE

    if isinstance(check, ThroughputMin):
        # Unreachable from the current subset: no entry carries this check any
        # more (see ``bench.subset.ThroughputMin``). Kept, with the probe it
        # drives, because it documents how a guaranteed floor was meant to be
        # observed. It is not evidence that guarantees are verified here.
        measured = parse_iperf_mbps(runner.iperf_contended(
            src, dst,
            _host(entry, check.contender_src),
            _host(entry, check.contender_dst),
        ))
        return measured >= check.min_mbps * FLOOR_TOLERANCE

    if isinstance(check, PortBlocked):
        blocked = _throughput_or_zero(runner.iperf(src, dst, port=check.port)) == 0.0
        reachable = parse_ping_loss(runner.ping(src, dst)) < 100.0
        return blocked and reachable

    if isinstance(check, PortOpen):
        # The dual of port_blocked, and for the same reason it conjoins two
        # conditions: base connectivity is total, so "this port carries
        # traffic" holds in the untouched network and measures nothing on its
        # own. It only becomes an observation about the plan once the denial
        # it is an exception to is in place.
        carries = _throughput_or_zero(runner.iperf(src, dst, port=check.port)) > 0.0
        isolated = parse_ping_loss(runner.ping(src, dst)) >= 100.0
        return carries and isolated

    if isinstance(check, MirrorSeen):
        seen = runner.tcpdump_count(
            check.probe_host, src, dst, tag=entry.intent_id
        )
        return seen >= check.min_packets

    if isinstance(check, PathUsed):
        mac_src = entry.endpoints[check.src].mac
        mac_dst = entry.endpoints[check.dst].mac
        # The runner's warmup runs before the plan is applied and nothing
        # crosses the diamond afterwards, so this check has to send its own
        # traffic. It also has to read a delta: the absolute counters carry
        # the warmup's packets, which took the default path, plus whatever
        # earlier checks of the same case generated. Only the increment is
        # attributable to the plan under test.
        via_before = runner.flow_packets(check.via, mac_src, mac_dst)
        not_via_before = runner.flow_packets(check.not_via, mac_src, mac_dst)
        runner.ping(src, dst)
        used = runner.flow_packets(check.via, mac_src, mac_dst) - via_before
        unused = runner.flow_packets(check.not_via, mac_src, mac_dst) - not_via_before
        if used == 0 and unused == 0:
            # Not "the model routed it the wrong way" but "the counters saw
            # nothing at all", which is what happens when no flow anywhere
            # matches the MAC pair. Returning False here would report a model
            # failure for a bench condition, so make it visible instead.
            raise VerifyError(
                f"no traffic observed on either path for "
                f"{mac_src} -> {mac_dst}: {check.via} and {check.not_via} "
                f"both report 0 new packets"
            )
        return used > 0 and unused == 0

    if isinstance(check, TosMarked):
        return runner.tos_of(src, dst) == check.tos

    raise VerifyError(f"unknown check {check!r}")
