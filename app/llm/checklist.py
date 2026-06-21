"""RocketEval checklist generation (full method, ADR-006 chantier 2).

The full RocketEval (ICLR 2025) pipeline grades a candidate answer against a
checklist of *intent-specific* verifiable criteria, rather than a fixed
generic list. This module produces that checklist: a strong model (via
OpenRouter) is asked to emit one yes/no criterion per line, including items
that specifically detect data fabrication and domain-level technical
correctness. The small local judge then grades each item (see
``judge.judge_rocketeval``).

Design choices, per project rules:
- ``client`` is injectable so tests run against httpx.MockTransport.
- Parsing is tolerant of common bullet/number prefixes and blank lines.
- An output that yields zero criteria raises :class:`ChecklistError`
  (never silently returns an empty checklist).
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from app import config
from app.llm.openrouter_client import call_model
from app.llm.schema import Intent

# Prompt asking the strong model for an intent-specific yes/no checklist.
# It must explicitly request fabrication-detection and domain-correctness
# items, and a one-criterion-per-line parsable format.
CHECKLIST_PROMPT_TEMPLATE = (
    "You are designing an evaluation checklist for answers given by a "
    "network-operations assistant. The assistant has NO live access to the "
    "network: it cannot read counters, telemetry, or current state.\n\n"
    "Below is one network intent. Produce a checklist of 5 to 8 criteria that "
    "a good answer to this intent MUST satisfy. Each criterion must be a "
    "single yes/no question that an independent grader can verify by reading "
    "the answer alone.\n\n"
    "Mandatory coverage:\n"
    "- Include at least one criterion that detects FABRICATION of data, e.g. "
    "'Does the response avoid inventing a numeric value it cannot know "
    "without live access?'.\n"
    "- Include at least one criterion checking that the response explains HOW "
    "to obtain the requested data (command, counter, API, tool) instead of "
    "inventing it.\n"
    "- Include at least one criterion on technical correctness for the "
    "specific network domain of the intent ({domain}: RAN, core, security, "
    "or slice).\n\n"
    "Output format: one criterion per line, each prefixed with '- '. No "
    "preamble, no numbering of sections, no closing remarks. Only the lines.\n\n"
    "Network intent (domain={domain}, criticality={criticality}): {text}\n\n"
    "Checklist:"
)

# Strips a leading bullet / number prefix from a single line.
# Handles: '- ', '* ', '• ', '1. ', '2) ', '3 - '.
_PREFIX_RE = re.compile(r"^\s*(?:[-*•]\s+|\d+\s*[.)\-]\s*)")


class ChecklistError(RuntimeError):
    """Raised when no verifiable criterion can be parsed from the model output."""


def _parse_lines(raw: str) -> tuple[str, ...]:
    """Extract one criterion per bulleted/numbered line; drop everything else.

    Only lines carrying a recognised bullet or number prefix are kept. This
    discards preamble such as 'Here is the checklist:' without guessing.
    """
    criteria: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        match = _PREFIX_RE.match(line)
        if match is None:
            continue
        criterion = line[match.end():].strip()
        if criterion:
            criteria.append(criterion)
    return tuple(criteria)


def generate_checklist(
    intent: Intent,
    *,
    client: Optional[httpx.Client] = None,
) -> tuple[str, ...]:
    """Generate an intent-specific RocketEval checklist via the strong model.

    Args:
        intent: The network intent to build the checklist for.
        client: Optional injected httpx.Client (for tests / connection reuse).

    Returns:
        An immutable tuple of verifiable yes/no criteria (one per element).

    Raises:
        OpenRouterError: on timeout, non-2xx status, or malformed response.
        ChecklistError: when the model output yields zero criteria.
    """
    prompt = CHECKLIST_PROMPT_TEMPLATE.format(
        domain=intent.domain,
        criticality=intent.criticality,
        text=intent.text,
    )
    response = call_model(
        config.CHECKLIST_MODEL,
        prompt,
        temperature=0.0,
        max_tokens=config.CHECKLIST_MAX_TOKENS,
        client=client,
    )
    criteria = _parse_lines(response.text)
    if not criteria:
        raise ChecklistError(
            "Checklist generation produced no verifiable criterion "
            f"(raw output: {response.text.strip()[:120]!r})."
        )
    return criteria
