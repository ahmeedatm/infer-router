"""Run one intent/strategy case against a live ONOS + Mininet runner."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.llm.sdn_action import SdnAction
from bench.onos_client import OnosClient
from bench.subset import SubsetEntry
from bench.translator import translate
from bench.verifier import (
    Measurements,
    decide,
    parse_iperf_mbps,
    parse_ping_loss,
)


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
    if gt.check == "throughput_min":
        return Measurements(throughput_mbps=parse_iperf_mbps(runner.iperf(src_host, dst_host)))
    return Measurements(loss_pct=parse_ping_loss(runner.ping(src_host, dst_host)))


def run_case(
    entry: SubsetEntry,
    action: SdnAction,
    strategy: str,
    onos: OnosClient,
    runner,
) -> CaseResult:
    """Apply the action on ONOS, measure the data plane, decide vs ground truth."""
    runner.warmup()
    cmd = translate(action, entry.endpoints)
    onos.execute(cmd)
    onos.wait_flows_installed(min_count=1, timeout_s=10.0)
    meas = _measure(entry, runner)
    satisfied = decide(entry.ground_truth, meas)
    return CaseResult(
        intent_id=entry.intent_id,
        strategy=strategy,
        satisfied=satisfied,
        detail=f"{action.action} {action.src}->{action.dst} | {meas.model_dump()}",
    )
