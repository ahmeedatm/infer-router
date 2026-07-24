"""Structured-output mode for the target LLM: it emits a network action
(allow/block/bandwidth between two logical endpoints) instead of prose.

Pure module: no network. The actual model call is wired by the phase-A
experiment script, which feeds the raw completion text to parse_action_response.
"""
from __future__ import annotations

import json
import re
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

Action = Literal["allow", "block", "bandwidth"]

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class SdnActionError(ValueError):
    """Raised when a raw completion cannot be parsed into a valid SdnAction."""


class SdnAction(BaseModel):
    """Immutable network action derived from an intent by the target LLM."""

    model_config = ConfigDict(frozen=True)

    intent_id: str
    action: Action
    src: str
    dst: str
    bw_mbps: Optional[float] = None


def build_action_prompt(intent_text: str, endpoint_ids: Sequence[str]) -> str:
    """Constrained-output prompt: force a single-line JSON network action."""
    ids = ", ".join(endpoint_ids)
    return (
        "You are a network controller. Read the intent and output ONLY a JSON "
        "object describing the network action it requires, nothing else.\n"
        'Schema: {"action": "allow|block|bandwidth", "src": <endpoint>, '
        '"dst": <endpoint>, "bw_mbps": <number, only for bandwidth>}\n'
        f"Valid endpoints: {ids}\n"
        f"Intent: {intent_text}\n"
        "JSON:"
    )


def parse_action_response(intent_id: str, raw: str) -> SdnAction:
    """Extract and validate the JSON action from a raw model completion."""
    match = _JSON_RE.search(raw)
    if match is None:
        raise SdnActionError(f"no JSON object found in completion: {raw[:120]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise SdnActionError(f"invalid JSON: {exc}") from exc
    try:
        return SdnAction(intent_id=intent_id, **data)
    except (ValidationError, TypeError) as exc:
        raise SdnActionError(f"action fails schema: {exc}") from exc
