from __future__ import annotations

from app.llm.sdn_action import SdnAction
from bench.orchestrator import CaseResult, run_case
from bench.subset import EndpointRef, GroundTruth, PingFail, SubsetEntry
from bench.translator import FlowSpec


def _entry() -> SubsetEntry:
    return SubsetEntry(
        intent_id="sec-001", text="block a->b", domain="security",
        criticality="high", klass="isolation", topology="linear3",
        expected_complexity="simple",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
        },
        checks=(PingFail(check="ping_fail", src="a", dst="b"),),
        ground_truth=GroundTruth(check="ping_fail", src="a", dst="b"),
    )


class _FakeRunner:
    """Records the applied FlowSpec and returns a canned ping output."""

    def __init__(self, ping_out: str) -> None:
        self._ping_out = ping_out
        self.applied: FlowSpec | None = None

    def warmup(self) -> None: ...
    def apply(self, spec: FlowSpec) -> None: self.applied = spec
    def ping(self, s, d) -> str: return self._ping_out
    def iperf(self, s, d) -> str: return ""


def test_isolation_satisfied_when_ping_fails():
    action = SdnAction(intent_id="sec-001", action="block", src="a", dst="b")
    runner = _FakeRunner("3 packets transmitted, 0 received, 100% packet loss")
    res = run_case(_entry(), action, "heavy", runner)
    assert isinstance(res, CaseResult)
    assert res.satisfied is True
    assert res.strategy == "heavy"
    assert runner.applied is not None and runner.applied.kind == "block"


def test_isolation_unsatisfied_when_ping_succeeds():
    action = SdnAction(intent_id="sec-001", action="block", src="a", dst="b")
    runner = _FakeRunner("3 packets transmitted, 3 received, 0% packet loss")
    res = run_case(_entry(), action, "light", runner)
    assert res.satisfied is False
