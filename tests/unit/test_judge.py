"""Unit tests for app.llm.judge (Ollama mocked via httpx.MockTransport)."""
from __future__ import annotations

import httpx
import pytest

from app.llm.judge import CHECKLIST, JudgeError, judge
from app.llm.schema import Intent, JudgeScore


def _intent() -> Intent:
    return Intent(
        id="ran-read-throughput",
        text="What is the current downlink throughput on cell gNB-042?",
        domain="ran",
        expected_complexity="simple",
        criticality="low",
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ollama_reply(content: str) -> dict:
    """Shape of an Ollama /api/chat non-streamed response."""
    return {"message": {"role": "assistant", "content": content}}


def _sequenced_handler(answers: list[str]):
    """Return a handler that yields the given answers in order, one per call."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = state["i"]
        state["i"] += 1
        return httpx.Response(200, json=_ollama_reply(answers[idx]))

    return handler


class TestJudgeAggregation:
    def test_three_yes_one_no_gives_q_075(self):
        # CHECKLIST has 4 criteria; answer YES,YES,YES,NO in order.
        handler = _sequenced_handler(["YES", "YES", "YES", "NO"])
        with _client(handler) as client:
            score = judge(_intent(), "Throughput is 142 Mbps.", client=client)

        assert isinstance(score, JudgeScore)
        assert score.q == pytest.approx(0.75)
        assert len(score.checklist) == len(CHECKLIST) == 4
        assert sum(score.checklist.values()) == 3

    def test_all_yes_gives_q_one(self):
        handler = _sequenced_handler(["YES"] * 4)
        with _client(handler) as client:
            score = judge(_intent(), "good", client=client)
        assert score.q == pytest.approx(1.0)
        assert all(score.checklist.values())

    def test_all_no_gives_q_zero(self):
        handler = _sequenced_handler(["NO"] * 4)
        with _client(handler) as client:
            score = judge(_intent(), "bad", client=client)
        assert score.q == pytest.approx(0.0)
        assert not any(score.checklist.values())


class TestParsingRobustness:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Yes.", True),
            ("YES", True),
            ("  YES\n", True),
            ("yes, definitely", True),
            ("no", False),
            ("No.", False),
            ("  NO ", False),
            ("nope, the answer is wrong", False),
        ],
    )
    def test_parses_variants(self, raw: str, expected: bool):
        handler = _sequenced_handler([raw, "NO", "NO", "NO"])
        with _client(handler) as client:
            score = judge(_intent(), "x", client=client)
        first_key = next(iter(CHECKLIST))
        assert score.checklist[first_key] is expected


class TestUnreadableOutputCountsNo:
    def test_unreadable_criterion_counts_no_without_exception(self):
        # First criterion returns gibberish with no yes/no -> counts NO.
        handler = _sequenced_handler(["maybe, it depends", "YES", "YES", "YES"])
        with _client(handler) as client:
            score = judge(_intent(), "x", client=client)
        first_key = next(iter(CHECKLIST))
        assert score.checklist[first_key] is False
        assert sum(score.checklist.values()) == 3
        assert score.q == pytest.approx(0.75)


class TestJudgeErrors:
    def test_network_error_raises_judge_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        with _client(handler) as client:
            with pytest.raises(JudgeError):
                judge(_intent(), "x", client=client)

    def test_http_500_raises_judge_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="ollama exploded")

        with _client(handler) as client:
            with pytest.raises(JudgeError) as exc:
                judge(_intent(), "x", client=client)
        assert "500" in str(exc.value)

    def test_malformed_json_raises_judge_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        with _client(handler) as client:
            with pytest.raises(JudgeError):
                judge(_intent(), "x", client=client)
