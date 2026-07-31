"""Shared prompt framing and model-id conventions for the LLM targets.

Extracted so the benchmark harness and the interactive CLI ask the pool models
exactly the same question. If the framing drifts between the two, a CLI demo
would no longer illustrate the numbers published in the report.

Model-id convention across the project:
- an OpenRouter id carries a ``/`` (``anthropic/claude-opus-4.8``),
- an Ollama tag carries a ``:`` (``qwen2.5:14b-instruct``),
- a domain specialist is the base id suffixed with ``#<domain>``.
"""
from __future__ import annotations

from app.llm.schema import Intent

# Operator framing prepended to every intent sent to a pool model. Kept
# identical to the framing used by every calibration and benchmark run so the
# CLI reproduces published conditions.
SYSTEM_PREFIX = (
    "You are a network operations assistant for a 5G/O-RAN operator. "
    "Answer the following operator intent precisely and concisely.\n\nIntent: "
)


def build_prompt(intent: Intent) -> str:
    """Build the full prompt sent to a pool model for ``intent``."""
    return f"{SYSTEM_PREFIX}{intent.text}"


def base_model_id(model_id: str) -> str:
    """Strip the domain suffix: ``'<heavy>#ran'`` -> ``'<heavy>'``."""
    return model_id.split("#", 1)[0]


def is_local_model_id(model_id: str) -> bool:
    """True when ``model_id`` is an Ollama tag rather than an OpenRouter id."""
    return ":" in model_id
