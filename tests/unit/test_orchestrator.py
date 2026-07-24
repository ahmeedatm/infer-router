from __future__ import annotations

import httpx

from app.llm.sdn_action import SdnAction
from bench.onos_client import OnosClient
from bench.orchestrator import CaseResult, run_case
from bench.subset import EndpointRef, GroundTruth, SubsetEntry


def _entry() -> SubsetEntry:
    return SubsetEntry(
        intent_id="sec-001", text="block a->b", domain="security",
        criticality="high", klass="isolation", topology="linear3",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
        },
        ground_truth=GroundTruth(check="ping_fail", src="a", dst="b"),
    )


class _FakeRunner:
    def __init__(self, ping_out: str) -> None:
        self._ping_out = ping_out
    def warmup(self) -> None: ...
    def ping(self, s, d) -> str: return self._ping_out
    def iperf(self, s, d) -> str: return ""


def _onos() -> OnosClient:
    def handler(request):
        if request.url.path == "/onos/v1/flows":
            return httpx.Response(200, json={"flows": [{"id": "1"}]})
        return httpx.Response(201, headers={"Location": "/x"})
    return OnosClient("http://onos",
                      client=httpx.Client(transport=httpx.MockTransport(handler),
                                          base_url="http://onos"))


def test_isolation_satisfied_when_ping_fails():
    action = SdnAction(intent_id="sec-001", action="block", src="a", dst="b")
    runner = _FakeRunner("3 packets transmitted, 0 received, 100% packet loss")
    res = run_case(_entry(), action, "heavy", _onos(), runner)
    assert isinstance(res, CaseResult)
    assert res.satisfied is True
    assert res.strategy == "heavy"


def test_isolation_unsatisfied_when_ping_succeeds():
    action = SdnAction(intent_id="sec-001", action="block", src="a", dst="b")
    runner = _FakeRunner("3 packets transmitted, 3 received, 0% packet loss")
    res = run_case(_entry(), action, "light", _onos(), runner)
    assert res.satisfied is False
