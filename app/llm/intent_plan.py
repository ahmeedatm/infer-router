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
over pure formatting when the intent only needed one operation. Extraction
uses a bracket-balanced, string-aware scan rather than a greedy regex: a
greedy first-bracket-to-last-bracket match is corrupted by any stray bracket
in surrounding prose (e.g. a citation like "[2]" or a literal "[" in an
endpoint name), which would silently bias failure counts against whichever
model tends to wrap its answers in more prose.
"""
from __future__ import annotations

import json
from typing import Annotated, Iterator, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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


def _matching_close(raw: str, start: int, open_char: str, close_char: str) -> Optional[int]:
    """Find the index that closes the bracket opened at ``start``.

    Tracks nesting depth for ``open_char``/``close_char`` only, and ignores
    both characters while inside a JSON string literal (honouring backslash
    escapes), so a bracket appearing inside a quoted value never perturbs the
    depth count. Returns ``None`` if the input runs out before depth returns
    to zero (unbalanced).
    """
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return i
    return None


def _iter_balanced_spans(raw: str, open_char: str, close_char: str) -> Iterator[str]:
    """Yield every balanced, string-aware span in ``raw``, in order of the
    opening bracket's position. Positions whose bracket never closes are
    skipped rather than raised, so the scan can keep looking further along
    the text for a real payload."""
    search_from = 0
    while True:
        start = raw.find(open_char, search_from)
        if start == -1:
            return
        end = _matching_close(raw, start, open_char, close_char)
        if end is not None:
            yield raw[start : end + 1]
        search_from = start + 1


def _first_valid_json(raw: str, open_char: str, close_char: str):
    """Return the parsed value of the first balanced span (in order of
    appearance) that is valid JSON, or ``None`` if no candidate parses.

    Trying every candidate span in turn, rather than only the first one, is
    what makes a stray unrelated bracket (a citation, a literal bracket in an
    endpoint name) harmless: a non-JSON candidate is simply skipped in favour
    of the next one.
    """
    for span in _iter_balanced_spans(raw, open_char, close_char):
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            continue
    return None


def _extract(raw: str) -> list:
    """Pull the operation list out of a completion.

    Prefers a JSON array anywhere in the text; a bare object is accepted only
    when no array is present, and is wrapped as a single-operation plan so a
    single-operation intent is not scored as a failure over pure formatting.
    Extraction is bracket-balanced and string-aware (see ``_matching_close``),
    not a greedy regex, so prose surrounding the payload cannot corrupt it.
    """
    data = _first_valid_json(raw, "[", "]")
    if data is None:
        data = _first_valid_json(raw, "{", "}")
    if data is None:
        raise IntentPlanError(f"no JSON found in completion: {raw[:120]!r}")
    return data if isinstance(data, list) else [data]


def parse_plan_response(intent_id: str, raw: str) -> IntentPlan:
    """Extract and validate the operation plan from a raw model completion."""
    operations = _extract(raw)
    try:
        return IntentPlan(intent_id=intent_id, operations=tuple(operations))
    except (ValidationError, TypeError) as exc:
        raise IntentPlanError(f"plan fails schema: {exc}") from exc
