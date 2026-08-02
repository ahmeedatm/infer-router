"""Tests for the shared prompt framing and model-id conventions."""
from __future__ import annotations

from app.llm.prompting import (
    SYSTEM_PREFIX,
    base_model_id,
    build_prompt,
    is_local_model_id,
)
from app.llm.schema import Intent


def _intent(text: str = "List the active cells on site A.") -> Intent:
    return Intent(
        id="INT-1",
        text=text,
        domain="ran",
        expected_complexity="simple",
        criticality="low",
    )


def test_build_prompt_prepends_operator_framing():
    prompt = build_prompt(_intent("Show PRB usage."))
    assert prompt == f"{SYSTEM_PREFIX}Show PRB usage."


def test_build_prompt_keeps_intent_text_verbatim():
    text = "Créer une slice URLLC < 5 ms pour l'usine X."
    assert build_prompt(_intent(text)).endswith(text)


def test_base_model_id_strips_domain_suffix():
    assert base_model_id("anthropic/claude-opus-4.8#ran") == "anthropic/claude-opus-4.8"


def test_base_model_id_leaves_plain_id_untouched():
    assert base_model_id("qwen/qwen-2.5-72b-instruct") == "qwen/qwen-2.5-72b-instruct"


def test_is_local_model_id_detects_ollama_tag():
    assert is_local_model_id("qwen2.5:14b-instruct") is True


def test_is_local_model_id_rejects_openrouter_id():
    assert is_local_model_id("anthropic/claude-opus-4.8") is False


class TestPromptFor:
    """A specialist id must actually change the framing sent.

    Regression guard for the defect this function was written to close: the
    pool advertised four domain specialists whose quality the router relied
    on, while every call went out with the generic framing.
    """

    def _intent(self):
        from app.llm.schema import Intent
        return Intent(id="i", text="Check RSRP on cell 42.", domain="ran",
                      expected_complexity="simple", criticality="low")

    def test_generic_id_gets_generic_framing(self):
        from app.llm.prompting import build_prompt, prompt_for
        intent = self._intent()
        assert prompt_for(intent, "anthropic/claude-opus-4.8") == build_prompt(intent)

    def test_specialist_id_gets_domain_expertise(self):
        from app.llm.prompting import build_prompt, prompt_for
        intent = self._intent()
        got = prompt_for(intent, "anthropic/claude-opus-4.8#ran")
        assert got != build_prompt(intent)
        assert "radio access network" in got
        assert intent.text in got

    def test_unknown_domain_falls_back_to_generic(self):
        from app.llm.prompting import build_prompt, prompt_for
        from app.llm.schema import Intent
        intent = Intent(id="i", text="x", domain="core",
                        expected_complexity="simple", criticality="low")
        object.__setattr__(intent, "domain", "unknown-domain")
        assert prompt_for(intent, "m#unknown-domain") == build_prompt(intent)
