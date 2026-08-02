# app/llm/intent_plan.py
"""Structured-output contract for the target LLM: an ordered plan of network
operations derived from one intent.

Replaces the earlier single-action contract, whose shape forced every
realisable intent to touch exactly two endpoints under one constraint, and so
made every bench intent structurally simple.

Pure module: no network. The model call is wired by the phase-A experiment
script, which feeds the raw completion text to ``parse_plan_response``.

``parse_plan_response`` deliberately accepts a bare JSON object (not just an
array) and wraps it as a single-operation plan. This avoids scoring a model
as failed over pure formatting when the intent only needed one operation.

Extraction is schema-aware, not just JSON-aware: it walks every balanced,
string-aware bracket span in the completion (arrays before bare objects) and
returns the first one that both parses as JSON and validates as an
``IntentPlan``. Two failure modes this avoids, both of which would bias
results against whichever model writes more prose around its answer (the
lighter, more verbose model in this project's benchmark):
- a greedy first-bracket-to-last-bracket regex, corrupted by any stray
  bracket anywhere in the completion (e.g. a citation like "[2]" or a
  literal "[" in an endpoint name);
- stopping at the first span that merely parses as *any* JSON, which is
  fooled by incidental bracketed content earlier in the text (a port list
  like "[80, 443]", an unrelated object) that is valid JSON but not a valid
  plan.

An array recognised as the model's answer is all-or-nothing. Its operations
are validated as a set, and a schema failure raises instead of falling
through to the bare-object branch: that fallthrough returned the first
standalone object that validated, so a four-operation plan containing one
malformed operation silently became a one-operation plan and scored as a
partial success. The bias ran the same way as the two above, against
multi-operation (complex) intents.
"""
from __future__ import annotations

import json
from typing import Annotated, Iterator, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class IntentPlanError(ValueError):
    """Raised when a raw completion cannot be parsed into a valid IntentPlan."""


class Selector(BaseModel):
    """Optional L4 narrowing of the flow an operation applies to."""

    model_config = ConfigDict(frozen=True)

    proto: Optional[Literal["tcp", "udp", "icmp"]] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def _port_needs_a_transport_proto(self) -> "Selector":
        """A port match without TCP or UDP is unrealisable.

        ``{"port": 22}`` alone becomes ``dl_type=0x0800,tp_dst=22`` and
        ``{"proto": "icmp", "port": 22}`` becomes ``nw_proto=1,tp_dst=22``;
        ovs-ofctl rejects both for missing prerequisites, so the rule is never
        installed. Rejecting the operation at parse time scores it as a model
        failure, which is what it is, instead of applying nothing and blaming
        the resulting check.
        """
        if self.port is not None and self.proto in (None, "icmp"):
            raise ValueError(
                f"selector port requires proto 'tcp' or 'udp' (got "
                f"{self.proto!r}): a port match has no meaning otherwise"
            )
        return self


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
    '"selector": {"proto": "tcp"|"udp"|"icmp", "port": <int>} (optional; '
    '"port" requires "proto" to be "tcp" or "udp")}',
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


def _iter_json_values(raw: str, open_char: str, close_char: str) -> Iterator[object]:
    """Yield every JSON value decodable from a balanced span in ``raw``, in
    order of appearance.

    A span that fails to parse as JSON at all is silently skipped here (it
    is never a real candidate); only spans that decode successfully are
    yielded, so the caller only has to reason about schema validity.
    """
    for span in _iter_balanced_spans(raw, open_char, close_char):
        try:
            yield json.loads(span)
        except json.JSONDecodeError:
            continue


def _is_the_models_answer(data: object) -> bool:
    """Is this decoded array the model's plan, or incidental bracketed text?

    The prompt asks for an array of operation objects, so an array qualifies
    when every element is an object and at least one carries the ``verb``
    discriminator. That skips the incidental content the scan is meant to
    step over (a port list like ``[80, 443]``, an array of unrelated
    records) without letting a genuine but malformed plan disguise itself as
    incidental.

    An empty array counts: the model answered, and its answer was "no
    operations", which the ``min_length`` rule reports far more usefully than
    "no JSON found".
    """
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        return False
    return not data or any("verb" in item for item in data)


def _describe(exc: ValidationError) -> str:
    """Name the offending operations, keeping pydantic's account of why.

    The index is what makes the failure actionable when a plan holds four
    operations; the underlying message is what tells a malformed completion
    apart from a bench problem in the VM run.
    """
    indices = sorted({
        error["loc"][1] for error in exc.errors()
        if len(error["loc"]) > 1 and isinstance(error["loc"][1], int)
    })
    if not indices:
        return str(exc)
    listed = ", ".join(str(i) for i in indices)
    return f"operation(s) at index {listed} invalid: {exc}"


def parse_plan_response(intent_id: str, raw: str) -> IntentPlan:
    """Extract and validate the operation plan from a raw model completion.

    Candidate selection is unchanged: array spans are considered before bare
    objects, each group in order of appearance, so incidental bracketed
    content elsewhere in the completion (a port list, an unrelated object)
    cannot shadow the real plan merely because it parses as JSON and comes
    first.

    What an array's schema failure means, however, is not a fallback. Once a
    span is recognised as the model's answer (see ``_is_the_models_answer``),
    its operations are validated as a set and a failure is terminal. Falling
    through to the bare-object branch used to return the first standalone
    object that validated, which silently truncated a four-operation plan to
    one and scored it as a partial success. A model that emitted four
    operations, one of them malformed, produced an unusable plan; that is a
    measured model failure and must be recorded as one.

    The bare-object branch remains for the case it was built for: a
    completion holding no array at all, where a single object is the whole
    answer.
    """
    for data in _iter_json_values(raw, "[", "]"):
        if not _is_the_models_answer(data):
            continue
        try:
            return IntentPlan(intent_id=intent_id, operations=tuple(data))
        except (ValidationError, TypeError) as exc:
            raise IntentPlanError(
                f"plan array rejected, {_describe(exc)}"
            ) from exc

    last_schema_error: Optional[Exception] = None
    for data in _iter_json_values(raw, "{", "}"):
        try:
            return IntentPlan(intent_id=intent_id, operations=(data,))
        except (ValidationError, TypeError) as exc:
            last_schema_error = exc
    if last_schema_error is not None:
        raise IntentPlanError(f"plan fails schema: {last_schema_error}") from last_schema_error
    raise IntentPlanError(f"no JSON found in completion: {raw[:120]!r}")
