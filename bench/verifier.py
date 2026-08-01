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
    SubsetEntry,
    ThroughputMax,
    ThroughputMin,
    TosMarked,
)

_LOSS_RE = re.compile(r"([\d.]+)%\s*packet loss")
_IPERF_RE = re.compile(r"([\d.]+)\s*Mbits/sec")

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
    m = _IPERF_RE.search(output)
    if m is None:
        raise VerifyError(f"no Mbits/sec field in iperf output: {output[:120]!r}")
    return float(m.group(1))


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

    if isinstance(check, MirrorSeen):
        return runner.tcpdump_count(check.probe_host, src, dst) >= check.min_packets

    if isinstance(check, PathUsed):
        mac_src = entry.endpoints[check.src].mac
        mac_dst = entry.endpoints[check.dst].mac
        used = runner.flow_packets(check.via, mac_src, mac_dst)
        unused = runner.flow_packets(check.not_via, mac_src, mac_dst)
        return used > 0 and unused == 0

    if isinstance(check, TosMarked):
        return runner.tos_of(src, dst) == check.tos

    raise VerifyError(f"unknown check {check!r}")
