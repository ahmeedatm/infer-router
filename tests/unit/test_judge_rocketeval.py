"""Unit tests for app.llm.judge.judge_rocketeval (all clients mocked)."""
from __future__ import annotations

import httpx
import pytest

from app.llm.judge import judge_rocketeval
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
    return {"message": {"role": "assistant", "content": content}}


def _sequenced_ollama_handler(answers: list[str]):
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = state["i"]
        state["i"] += 1
        return httpx.Response(200, json=_ollama_reply(answers[idx]))

    return handler


class TestJudgeRocketevalWithProvidedChecklist:
    def test_q_is_yes_over_total(self):
        checklist = (
            "Does the response avoid inventing a numeric value?",
            "Does the response explain how to obtain the metric?",
            "Is the answer technically correct for the RAN domain?",
            "Is the answer complete?",
        )
        ollama = _sequenced_ollama_handler(["YES", "NO", "YES", "NO"])
        with _client(ollama) as ollama_client:
            score = judge_rocketeval(
                _intent(),
                "Throughput is 142 Mbps.",
                checklist=checklist,
                ollama_client=ollama_client,
            )

        assert isinstance(score, JudgeScore)
        assert score.q == pytest.approx(0.5)
        assert len(score.checklist) == 4
        assert score.checklist[checklist[0]] is True
        assert score.checklist[checklist[1]] is False
        assert score.checklist[checklist[2]] is True
        assert score.checklist[checklist[3]] is False

    def test_all_yes_gives_q_one(self):
        checklist = ("a?", "b?", "c?")
        ollama = _sequenced_ollama_handler(["YES", "YES", "YES"])
        with _client(ollama) as ollama_client:
            score = judge_rocketeval(
                _intent(), "good", checklist=checklist, ollama_client=ollama_client
            )
        assert score.q == pytest.approx(1.0)
        assert all(score.checklist.values())

    def test_does_not_call_openrouter_when_checklist_given(self):
        # An OpenRouter client that would explode if touched.
        def exploding(request: httpx.Request) -> httpx.Response:
            raise AssertionError("OpenRouter must not be called when checklist provided")

        ollama = _sequenced_ollama_handler(["YES"])
        with _client(ollama) as ollama_client, _client(exploding) as or_client:
            score = judge_rocketeval(
                _intent(),
                "x",
                checklist=("only one?",),
                openrouter_client=or_client,
                ollama_client=ollama_client,
            )
        assert score.q == pytest.approx(1.0)


class TestJudgeRocketevalGeneratesChecklist:
    def test_generates_checklist_when_none(self):
        # OpenRouter returns a 2-item checklist; Ollama grades YES, NO.
        def openrouter_handler(request: httpx.Request) -> httpx.Response:
            content = "- Criterion one?\n- Criterion two?"
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                },
            )

        ollama = _sequenced_ollama_handler(["YES", "NO"])
        with _client(openrouter_handler) as or_client, _client(ollama) as ollama_client:
            score = judge_rocketeval(
                _intent(),
                "some answer",
                openrouter_client=or_client,
                ollama_client=ollama_client,
            )

        assert set(score.checklist) == {"Criterion one?", "Criterion two?"}
        assert score.checklist["Criterion one?"] is True
        assert score.checklist["Criterion two?"] is False
        assert score.q == pytest.approx(0.5)
