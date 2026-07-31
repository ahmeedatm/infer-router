"""Data-plane verification: run one ground-truth check against the network.

Two APIs coexist here, mirroring the two ``SubsetEntry`` schemas (see
``bench.subset``):

- Legacy: ``GroundTruth`` + ``Measurements`` + :func:`decide`, still consumed
  by :mod:`bench.orchestrator`. Removed once orchestrator migrates (cleanup
  task).
- Current: :func:`run_check` drives a check straight from ``entry.checks``
  through the runner protocol and decides in one step, without an
  intermediate ``Measurements`` object. Each check derives from the intent's
  ground truth, never from the plan the model produced.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict

from bench.subset import (
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

_LOSS_RE = re.compile(r"([\d.]+)%\s*packet loss")
_IPERF_RE = re.compile(r"([\d.]+)\s*Mbits/sec")

# Policing and measurement overshoot the cap slightly; htb floors undershoot.
THROUGHPUT_TOLERANCE = 1.15
FLOOR_TOLERANCE = 0.85


class VerifyError(ValueError):
    """Raised when a command output cannot be parsed."""


class Measurements(BaseModel):
    model_config = ConfigDict(frozen=True)
    loss_pct: Optional[float] = None
    throughput_mbps: Optional[float] = None


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
        return runner.tcpdump_count(check.probe_host) >= check.min_packets

    if isinstance(check, PathUsed):
        mac_src = entry.endpoints[check.src].mac
        mac_dst = entry.endpoints[check.dst].mac
        used = runner.flow_packets(check.via, mac_src, mac_dst)
        unused = runner.flow_packets(check.not_via, mac_src, mac_dst)
        return used > 0 and unused == 0

    if isinstance(check, TosMarked):
        return runner.tos_of(src, dst) == check.tos

    raise VerifyError(f"unknown check {check!r}")


def decide(ground_truth: GroundTruth, meas: Measurements) -> bool:
    """Return True iff the measurement satisfies the intent's ground truth."""
    if ground_truth.check == "ping_ok":
        return meas.loss_pct is not None and meas.loss_pct < 100.0
    if ground_truth.check == "ping_fail":
        return meas.loss_pct is not None and meas.loss_pct >= 100.0
    if ground_truth.check == "throughput_min":
        floor = ground_truth.min_mbps or 0.0
        return meas.throughput_mbps is not None and meas.throughput_mbps >= floor
    if ground_truth.check == "throughput_max":
        if ground_truth.max_mbps is None:
            raise VerifyError("throughput_max requires max_mbps")
        # 15% tolerance above the cap to absorb policing/measurement overshoot.
        ceiling = ground_truth.max_mbps * 1.15
        return meas.throughput_mbps is not None and meas.throughput_mbps <= ceiling
    raise VerifyError(f"unknown check {ground_truth.check!r}")
