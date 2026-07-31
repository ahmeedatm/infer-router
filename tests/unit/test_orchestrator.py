from __future__ import annotations

from app.llm.intent_plan import parse_plan_response
from bench.orchestrator import CaseResult, run_case
from bench.subset import EndpointRef, PingFail, SubsetEntry, ThroughputMax

_OK = "3 packets transmitted, 3 received, 0% packet loss"
_LOST = "3 packets transmitted, 0 received, 100% packet loss"


def _entry() -> SubsetEntry:
    return SubsetEntry(
        intent_id="cx-001", text="isolate and cap", domain="security",
        criticality="high", expected_complexity="complex", topology="diamond4",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
        },
        checks=(
            PingFail(check="ping_fail", src="a", dst="b"),
            ThroughputMax(check="throughput_max", src="a", dst="b", max_mbps=10.0),
        ),
    )


class _FakeRunner:
    def __init__(self, ping_out: str, iperf_out: str) -> None:
        self._ping, self._iperf = ping_out, iperf_out
        self.applied = []
        self.warmup_calls = 0

    def warmup(self): self.warmup_calls += 1
    def apply(self, commands): self.applied.extend(commands)
    def ping(self, s, d): return self._ping
    def iperf(self, s, d, port=None, seconds=5): return self._iperf


_FULL = ('[{"verb": "block", "src": "a", "dst": "b"}, '
         '{"verb": "bandwidth_max", "src": "a", "dst": "b", "bw_mbps": 10}]')


def test_both_checks_pass_gives_satisfied_and_rate_one():
    runner = _FakeRunner(_LOST, "9.0 Mbits/sec")
    res = run_case(_entry(), parse_plan_response("cx-001", _FULL), "heavy", runner)
    assert isinstance(res, CaseResult)
    assert res.satisfied is True
    assert res.realization_rate == 1.0
    assert res.expected_complexity == "complex"
    assert len(runner.applied) == 3


def test_one_check_out_of_two_gives_unsatisfied_but_half_rate():
    # The model only blocked; the cap is missing, so throughput overshoots.
    partial = '[{"verb": "block", "src": "a", "dst": "b"}]'
    runner = _FakeRunner(_LOST, "45.0 Mbits/sec")
    res = run_case(_entry(), parse_plan_response("cx-001", partial), "light", runner)
    assert res.satisfied is False
    assert res.realization_rate == 0.5


def test_a_missing_plan_counts_as_a_total_failure():
    res = run_case(_entry(), None, "light", _FakeRunner(_OK, ""))
    assert res.satisfied is False
    assert res.realization_rate == 0.0
    assert "no valid plan" in res.detail


def test_an_untranslatable_plan_counts_as_a_total_failure():
    bad = '[{"verb": "block", "src": "a", "dst": "ghost"}]'
    res = run_case(_entry(), parse_plan_response("cx-001", bad), "light",
                   _FakeRunner(_OK, ""))
    assert res.satisfied is False
    assert res.realization_rate == 0.0
    assert "unknown endpoint" in res.detail


def test_an_unreadable_probe_fails_only_that_check():
    # ping output has no packet-loss field: parse_ping_loss raises VerifyError
    # for the ping_fail check. The iperf output is well-formed, so the
    # throughput_max check still gets a genuine verdict. One bad probe must
    # cost exactly one check, not the whole case.
    runner = _FakeRunner("connect: Network is unreachable", "9.0 Mbits/sec")
    res = run_case(_entry(), parse_plan_response("cx-001", _FULL), "heavy", runner)
    assert res.satisfied is False
    assert res.realization_rate == 0.5


def test_a_missing_plan_causes_no_runner_side_effects():
    runner = _FakeRunner(_OK, "")
    run_case(_entry(), None, "light", runner)
    assert runner.warmup_calls == 0
    assert runner.applied == []
