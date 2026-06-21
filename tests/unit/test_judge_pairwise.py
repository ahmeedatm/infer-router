"""Unit tests for app.llm.judge.judge_pairwise (Ollama mocked).

judge_pairwise makes TWO judge calls per evaluation (order A,B then B,A) to
cancel the position bias, so the mock handlers below feed a *pair* of verdicts.
"""
from __future__ import annotations

import httpx
import pytest

from app.llm.judge import JudgeError, judge_pairwise
from app.llm.schema import Intent


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
    return {"message": {"role": "assistant", "content": content}}


def _sequenced_ollama_handler(answers: list[str]):
    """Return successive canned verdicts, one per /api/chat call."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = state["i"]
        state["i"] += 1
        return httpx.Response(200, json=_ollama_reply(answers[idx]))

    return handler


class TestPairwiseAgreementAcrossOrders:
    def test_both_orders_favour_a_returns_a(self):
        # 1st call order (A,B): judge picks the winner shown as "A" -> "A".
        # 2nd call order (B,A): the correct text is now shown as "B" -> "B".
        ollama = _sequenced_ollama_handler(["A", "B"])
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(), "good answer", "bad answer", ollama_client=client
            )
        assert verdict == "A"

    def test_both_orders_favour_b_returns_b(self):
        # 1st call (A,B) picks "B"; 2nd call (B,A) picks "A" (same real text).
        ollama = _sequenced_ollama_handler(["B", "A"])
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(), "bad answer", "good answer", ollama_client=client
            )
        assert verdict == "B"

    def test_orders_disagree_returns_tie(self):
        # Both calls say "A": after de-swapping the 2nd, they point to opposite
        # real responses -> inconsistent -> tie.
        ollama = _sequenced_ollama_handler(["A", "A"])
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(), "resp one", "resp two", ollama_client=client
            )
        assert verdict == "tie"

    def test_explicit_tie_in_first_order_returns_tie(self):
        ollama = _sequenced_ollama_handler(["TIE", "A"])
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(), "resp one", "resp two", ollama_client=client
            )
        assert verdict == "tie"


class TestPairwiseParsing:
    @pytest.mark.parametrize(
        "first, second, expected",
        [
            ("A", "B", "A"),
            ("Response A is better.", "Response B is better.", "A"),
            (" b ", " a ", "B"),
            ("TIE", "A", "tie"),
            ("The winner is B.", "The winner is A.", "B"),
        ],
    )
    def test_parses_free_text_verdicts(self, first, second, expected):
        ollama = _sequenced_ollama_handler([first, second])
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(), "first text", "second text", ollama_client=client
            )
        assert verdict == expected

    def test_unreadable_output_returns_tie(self):
        ollama = _sequenced_ollama_handler(["maybe?", "who knows"])
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(), "first", "second", ollama_client=client
            )
        assert verdict == "tie"


class TestPairwiseChecklist:
    def test_checklist_is_accepted(self):
        ollama = _sequenced_ollama_handler(["A", "B"])
        checklist = ("Is it correct?", "Is it complete?")
        with _client(ollama) as client:
            verdict = judge_pairwise(
                _intent(),
                "good",
                "bad",
                checklist=checklist,
                ollama_client=client,
            )
        assert verdict == "A"


class TestPairwiseHardErrors:
    def test_network_error_raises_judge_error(self):
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("ollama down")

        with _client(boom) as client:
            with pytest.raises(JudgeError):
                judge_pairwise(_intent(), "a", "b", ollama_client=client)

    def test_non_2xx_status_raises_judge_error(self):
        def server_error(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with _client(server_error) as client:
            with pytest.raises(JudgeError):
                judge_pairwise(_intent(), "a", "b", ollama_client=client)
