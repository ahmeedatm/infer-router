# app/llm/intent_plan.py
"""Structured-output contract for the target LLM: an ordered plan of network
operations derived from one intent.

Replaces the single-action ``SdnAction`` contract, whose shape forced every
realisable intent to touch exactly two endpoints under one constraint, and so
made every bench intent structurally simple.

Pure module: no network. The model call is wired by the phase-A experiment
script, which feeds the raw completion text to ``parse_plan_response``.

``_extract`` deliberately accepts a bare JSON object (not just an array) and
wraps it as a single-operation plan. This avoids scoring a model as failed
over pure formatting when the intent only needed one operation.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class IntentPlanError(ValueError):
    """Raised when a raw completion cannot be parsed into a valid IntentPlan."""


class Selector(BaseModel):
    """Optional L4 narrowing of the flow an operation applies to."""

    model_config = ConfigDict(frozen=True)

    proto: Optional[Literal["tcp", "udp", "icmp"]] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)


class _BaseOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    src: str
    dst: str


class AllowOp(_BaseOp):
    verb: Literal["allow"]
    selector: Optional[Selector] = None


class BlockOp(_BaseOp):
    verb: Literal["block"]
    selector: Optional[Selector] = None


class BandwidthMaxOp(_BaseOp):
    verb: Literal["bandwidth_max"]
    bw_mbps: float = Field(gt=0)


class BandwidthMinOp(_BaseOp):
    verb: Literal["bandwidth_min"]
    bw_mbps: float = Field(gt=0)


class MirrorOp(_BaseOp):
    verb: Literal["mirror"]
    to: str


class RerouteOp(_BaseOp):
    verb: Literal["reroute"]
    via: str


class PriorityOp(_BaseOp):
    verb: Literal["priority"]
    klass: Literal["high", "normal", "low"]


Operation = Annotated[
    Union[
        AllowOp, BlockOp, BandwidthMaxOp, BandwidthMinOp,
        MirrorOp, RerouteOp, PriorityOp,
    ],
    Field(discriminator="verb"),
]


class IntentPlan(BaseModel):
    """Immutable ordered plan of network operations for one intent."""

    model_config = ConfigDict(frozen=True)

    intent_id: str
    operations: tuple[Operation, ...] = Field(min_length=1)


_SCHEMA_LINES = (
    '{"verb": "allow"|"block", "src": <endpoint>, "dst": <endpoint>, '
    '"selector": {"proto": "tcp"|"udp"|"icmp", "port": <int>} (optional)}',
    '{"verb": "bandwidth_max"|"bandwidth_min", "src": <endpoint>, '
    '"dst": <endpoint>, "bw_mbps": <number>}',
    '{"verb": "mirror", "src": <endpoint>, "dst": <endpoint>, "to": <endpoint>}',
    '{"verb": "reroute", "src": <endpoint>, "dst": <endpoint>, "via": <switch>}',
    '{"verb": "priority", "src": <endpoint>, "dst": <endpoint>, '
    '"klass": "high"|"normal"|"low"}',
)


def build_plan_prompt(intent_text: str, endpoint_ids: Sequence[str]) -> str:
    """Constrained-output prompt: force a JSON array of network operations."""
    ids = ", ".join(endpoint_ids)
    schema = "\n".join(f"  {line}" for line in _SCHEMA_LINES)
    return (
        "You are a network controller. Read the intent and output ONLY a JSON "
        "array of the network operations it requires, nothing else.\n"
        "Emit one object per operation the intent demands; an intent may need "
        "several.\n"
        f"Operation schemas:\n{schema}\n"
        f"Valid endpoints: {ids}\n"
        f"Intent: {intent_text}\n"
        "JSON array:"
    )


def _extract(raw: str) -> list:
    """Pull the operation list out of a completion.

    A bare object is accepted and wrapped, so that a single-operation intent is
    not scored as a failure over pure formatting. Anything else is an error.
    """
    match = _ARRAY_RE.search(raw)
    if match is not None:
        payload = match.group(0)
    else:
        obj = _OBJECT_RE.search(raw)
        if obj is None:
            raise IntentPlanError(f"no JSON found in completion: {raw[:120]!r}")
        payload = obj.group(0)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise IntentPlanError(f"invalid JSON: {exc}") from exc
    return data if isinstance(data, list) else [data]


def parse_plan_response(intent_id: str, raw: str) -> IntentPlan:
    """Extract and validate the operation plan from a raw model completion."""
    operations = _extract(raw)
    try:
        return IntentPlan(intent_id=intent_id, operations=tuple(operations))
    except (ValidationError, TypeError) as exc:
        raise IntentPlanError(f"plan fails schema: {exc}") from exc
