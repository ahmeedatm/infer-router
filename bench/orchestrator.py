"""Run one intent/strategy case on the OVS bench (no external controller)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.llm.sdn_action import SdnAction
from bench.subset import SubsetEntry
from bench.translator import translate
from bench.verifier import (
    Measurements,
    decide,
    parse_iperf_mbps,
    parse_ping_loss,
)

_THROUGHPUT_CHECKS = ("throughput_min", "throughput_max")


class CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_id: str
    strategy: str
    satisfied: bool
    detail: str


def _measure(entry: SubsetEntry, runner) -> Measurements:
    gt = entry.ground_truth
    src_host = entry.endpoints[gt.src].host
    dst_host = entry.endpoints[gt.dst].host
    if gt.check in _THROUGHPUT_CHECKS:
        return Measurements(throughput_mbps=parse_iperf_mbps(runner.iperf(src_host, dst_host)))
    return Measurements(loss_pct=parse_ping_loss(runner.ping(src_host, dst_host)))


def run_case(
    entry: SubsetEntry,
    action: SdnAction,
    strategy: str,
    runner,
) -> CaseResult:
    """Apply the action on the data plane, measure it, decide vs ground truth.

    ``runner`` exposes ``warmup()``, ``apply(FlowSpec)``, ``ping()`` and
    ``iperf()`` (see :class:`bench.topology.MininetRunner`). Unit tests inject a
    fake runner, so this stays free of any Mininet dependency.
    """
    runner.warmup()
    spec = translate(action, entry.endpoints)
    runner.apply(spec)
    meas = _measure(entry, runner)
    satisfied = decide(entry.ground_truth, meas)
    return CaseResult(
        intent_id=entry.intent_id,
        strategy=strategy,
        satisfied=satisfied,
        detail=f"{action.action} {action.src}->{action.dst} | {meas.model_dump()}",
    )
