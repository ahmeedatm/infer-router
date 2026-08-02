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
