"""Unit tests for app.llm.checklist (OpenRouter mocked, no real network)."""
from __future__ import annotations

import httpx
import pytest

from app.llm.checklist import ChecklistError, generate_checklist
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


def _openrouter_reply(content: str) -> dict:
    """Shape of an OpenRouter chat-completions non-streamed response."""
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 60},
    }


def _handler_returning(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openrouter_reply(content))

    return handler


class TestGenerateChecklistNominal:
    def test_parses_dash_prefixed_lines(self):
        raw = (
            "- Does the response avoid inventing a numeric value?\n"
            "- Does the response explain how to obtain the metric?\n"
            "- Is the answer technically correct for the RAN domain?"
        )
        with _client(_handler_returning(raw)) as client:
            checklist = generate_checklist(_intent(), client=client)

        assert isinstance(checklist, tuple)
        assert len(checklist) == 3
        assert checklist[0] == "Does the response avoid inventing a numeric value?"
        assert checklist[1] == "Does the response explain how to obtain the metric?"
        assert checklist[2] == "Is the answer technically correct for the RAN domain?"

    def test_uses_checklist_model_and_zero_temperature(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200, json=_openrouter_reply("- One verifiable criterion?")
            )

        from app import config

        with _client(handler) as client:
            generate_checklist(_intent(), client=client)

        assert captured["body"]["model"] == config.CHECKLIST_MODEL
        assert captured["body"]["temperature"] == 0.0


class TestParsingTolerance:
    def test_numbered_lines_and_blank_lines(self):
        raw = (
            "1. First verifiable criterion?\n"
            "\n"
            "2) Second verifiable criterion?\n"
            "   \n"
            "3 - Third verifiable criterion?\n"
        )
        with _client(_handler_returning(raw)) as client:
            checklist = generate_checklist(_intent(), client=client)

        assert checklist == (
            "First verifiable criterion?",
            "Second verifiable criterion?",
            "Third verifiable criterion?",
        )

    def test_star_and_asterisk_bullets(self):
        raw = "* Criterion A?\n• Criterion B?\n"
        with _client(_handler_returning(raw)) as client:
            checklist = generate_checklist(_intent(), client=client)
        assert checklist == ("Criterion A?", "Criterion B?")

    def test_strips_surrounding_whitespace_and_skips_header_noise(self):
        raw = (
            "Here is the checklist:\n"
            "- Real criterion one?\n"
            "- Real criterion two?\n"
        )
        with _client(_handler_returning(raw)) as client:
            checklist = generate_checklist(_intent(), client=client)
        # The non-bulleted preamble line is dropped; only bullets are kept.
        assert checklist == ("Real criterion one?", "Real criterion two?")


class TestGenerateChecklistErrors:
    def test_empty_output_raises_checklist_error(self):
        with _client(_handler_returning("")) as client:
            with pytest.raises(ChecklistError):
                generate_checklist(_intent(), client=client)

    def test_only_whitespace_and_noise_raises_checklist_error(self):
        # No bulleted/numbered line at all -> zero parsed criteria.
        with _client(_handler_returning("   \n\n  \n")) as client:
            with pytest.raises(ChecklistError):
                generate_checklist(_intent(), client=client)
