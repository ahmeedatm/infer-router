"""Data-plane verification: parse ping/iperf output, decide vs ground truth."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict

from bench.subset import GroundTruth

_LOSS_RE = re.compile(r"([\d.]+)%\s*packet loss")
_IPERF_RE = re.compile(r"([\d.]+)\s*Mbits/sec")


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


def decide(ground_truth: GroundTruth, meas: Measurements) -> bool:
    """Return True iff the measurement satisfies the intent's ground truth."""
    if ground_truth.check == "ping_ok":
        return meas.loss_pct is not None and meas.loss_pct < 100.0
    if ground_truth.check == "ping_fail":
        return meas.loss_pct is not None and meas.loss_pct >= 100.0
    if ground_truth.check == "throughput_min":
        floor = ground_truth.min_mbps or 0.0
        return meas.throughput_mbps is not None and meas.throughput_mbps >= floor
    raise VerifyError(f"unknown check {ground_truth.check!r}")
