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


# Domain expertise prepended for a specialist target. Until this existed, a
# "specialist" was purely nominal: the pool suffixed a model id with #<domain>,
# base_model_id() stripped the suffix before the call, and every tier received
# the same SYSTEM_PREFIX. Contribution C2 could therefore never be measured,
# only assumed through the hardcoded quality constants in app.config.
SPECIALIST_EXPERTISE: dict[str, str] = {
    "ran": (
        "You specialise in the radio access network: gNB and cell "
        "configuration, RSRP/RSRQ/SINR, handover and mobility parameters, "
        "scheduler behaviour, PRB utilisation and radio KPIs."
    ),
    "core": (
        "You specialise in the 5G core: AMF, SMF, UPF and PCF procedures, "
        "PDU session and bearer handling, N-interfaces, subscriber state, "
        "and control-plane signalling."
    ),
    "security": (
        "You specialise in network security: segmentation and isolation "
        "policy, access control and filtering rules, anomaly and intrusion "
        "signals, incident containment, and audit trails."
    ),
    "slice": (
        "You specialise in network slicing: eMBB, URLLC and mMTC slice "
        "profiles, SLA parameters and their enforcement, slice isolation, "
        "resource partitioning and admission control."
    ),
}


def build_specialist_prompt(intent: Intent) -> str:
    """Prompt for a domain specialist target.

    Falls back to the generic framing when the intent's domain has no declared
    expertise, so an unknown domain degrades to the generic tier rather than
    silently losing the operator framing.
    """
    expertise = SPECIALIST_EXPERTISE.get(intent.domain)
    if expertise is None:
        return build_prompt(intent)
    return (
        "You are a network operations assistant for a 5G/O-RAN operator. "
        f"{expertise} "
        "Answer the following operator intent precisely and concisely.\n\n"
        f"Intent: {intent.text}"
    )


def prompt_for(intent: Intent, model_id: str) -> str:
    """Framing to send to ``model_id`` for ``intent``.

    Single place where a pool id decides the framing. A specialist id carries
    a ``#<domain>`` suffix, and until this existed the suffix was purely
    nominal: base_model_id stripped it before the call and every tier got the
    generic framing, so a "specialist" was the generic model under another
    name. Route every call site through here so the pool's promise and the
    request actually sent cannot drift apart again.
    """
    if "#" in model_id:
        return build_specialist_prompt(intent)
    return build_prompt(intent)
