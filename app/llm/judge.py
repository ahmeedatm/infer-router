"""Local LLM-Judge wrapper (simplified RocketEval) for the spike.

RocketEval (ICLR 2025) grades a candidate answer against a checklist of
verifiable criteria, each answered YES/NO by a small local model, then
aggregates them into a scalar quality score. This module ships a
*simplified* version for the spike: a fixed, generic 4-item checklist
scored by the Ollama judge model, aggregated as ``q = #YES / #total``.

Design choices, per project rules:
- ``client`` is injectable so tests run against httpx.MockTransport.
- A criterion whose grading output is unreadable counts as NO and is
  logged (it must not break the whole batch).
- Ollama being unreachable, or returning a non-2xx / non-JSON payload,
  raises :class:`JudgeError` (a hard, distinct failure).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from app import config
from app.llm.checklist import generate_checklist
from app.llm.schema import Intent, JudgeScore

logger = logging.getLogger(__name__)

# Generic checklist: ordered mapping criterion-key -> human description.
# Each is graded independently and answered strictly YES/NO by the judge.
CHECKLIST: dict[str, str] = {
    "technical_correctness": (
        "The response is technically correct with respect to what the "
        "network intent asks for."
    ),
    "completeness": (
        "The response fully addresses the intent and leaves no essential "
        "part unanswered."
    ),
    "domain_fit": (
        "The response is appropriate for the network domain of the intent "
        "(RAN, core, security, or slice)."
    ),
    "no_hallucination": (
        "The response does not invent facts, entities, or values that are "
        "not warranted by the intent."
    ),
}

_GRADING_INSTRUCTION = (
    "You are a strict evaluator of network-operations assistant answers. "
    "Decide whether the candidate response satisfies the criterion below. "
    "Answer with a single word: YES or NO. Do not explain."
)

# Word-boundary matching so 'yes'/'no' inside other words are ignored.
_YES_RE = re.compile(r"\byes\b", re.IGNORECASE)
_NO_RE = re.compile(r"\bno\b|\bnope\b", re.IGNORECASE)


def _build_prompt(intent: Intent, response_text: str, criterion: str) -> str:
    """Compose the grading prompt for one checklist criterion."""
    return (
        f"{_GRADING_INSTRUCTION}\n\n"
        f"Network intent ({intent.domain}): {intent.text}\n\n"
        f"Candidate response: {response_text}\n\n"
        f"Criterion: {criterion}\n\n"
        f"Answer (YES or NO):"
    )


def _endpoint() -> str:
    """Absolute Ollama chat URL, built from config (never relative)."""
    return f"{config.OLLAMA_HOST.rstrip('/')}/api/chat"


def _ask_judge(prompt: str, client: httpx.Client) -> str:
    """Send one prompt to the local judge and return its raw text reply.

    Centralises the Ollama /api/chat round-trip (used by both the YES/NO
    grading path and the pairwise path). Raises JudgeError only for hard
    failures (network, non-2xx status, malformed JSON), never for content.
    """
    body = {
        "model": config.JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        response = client.post(_endpoint(), json=body)
    except httpx.HTTPError as exc:
        raise JudgeError(f"Ollama request failed at {_endpoint()}: {exc}") from exc

    if response.status_code >= 400:
        raise JudgeError(
            f"Ollama returned status {response.status_code}: {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise JudgeError(f"Ollama response is not valid JSON: {exc}") from exc

    return _extract_content(payload)


def _grade_one(intent: Intent, response_text: str, criterion: str, client: httpx.Client) -> bool:
    """Ask the judge to grade one criterion. Unreadable output -> NO (logged).

    Raises JudgeError only for hard failures (network, status, bad JSON),
    which must abort the whole evaluation rather than be silently scored NO.
    """
    content = _ask_judge(_build_prompt(intent, response_text, criterion), client)
    return _parse_yes_no(content, criterion)


def _extract_content(payload: object) -> str:
    """Pull the assistant text out of an Ollama /api/chat payload."""
    if not isinstance(payload, dict):
        raise JudgeError("Unexpected Ollama payload (not a JSON object).")
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    # /api/generate fallback shape.
    if isinstance(payload.get("response"), str):
        return payload["response"]
    raise JudgeError("Ollama payload is missing message content.")


def _parse_yes_no(content: str, criterion: str) -> bool:
    """Interpret a small model's free text as a YES/NO verdict.

    Tolerates case, punctuation, surrounding whitespace and short trailing
    text ('Yes.', 'no, the answer is wrong'). YES wins only when a yes
    token is present and no contradicting no token is. Anything unreadable
    counts as NO and is logged (never raised).
    """
    has_yes = bool(_YES_RE.search(content))
    has_no = bool(_NO_RE.search(content))
    if has_yes and not has_no:
        return True
    if has_no and not has_yes:
        return False
    logger.warning(
        "Unreadable judge verdict for criterion %r (raw=%r) -> counting NO.",
        criterion,
        content.strip()[:80],
    )
    return False


class JudgeError(RuntimeError):
    """Raised for hard judge failures (Ollama unreachable, bad status/JSON)."""


def judge(
    intent: Intent,
    response_text: str,
    *,
    client: Optional[httpx.Client] = None,
) -> JudgeScore:
    """Score a candidate response against the intent via the local judge.

    Args:
        intent: The network intent the response is meant to satisfy.
        response_text: Candidate answer to evaluate.
        client: Optional injected httpx.Client (for tests / reuse).

    Returns:
        A JudgeScore with q = (#YES / #criteria) and the per-criterion checklist.

    Raises:
        JudgeError: Ollama unreachable, non-2xx status, or malformed JSON.
    """
    owns_client = client is None
    active = client or httpx.Client(timeout=config.OPENROUTER_TIMEOUT_S)
    try:
        checklist = {
            key: _grade_one(intent, response_text, description, active)
            for key, description in CHECKLIST.items()
        }
    finally:
        if owns_client:
            active.close()

    q = sum(checklist.values()) / len(checklist)
    return JudgeScore(q=q, checklist=checklist)


def judge_rocketeval(
    intent: Intent,
    response_text: str,
    *,
    checklist: Optional[tuple[str, ...]] = None,
    openrouter_client: Optional[httpx.Client] = None,
    ollama_client: Optional[httpx.Client] = None,
) -> JudgeScore:
    """Score a response with the full RocketEval method (per-intent checklist).

    Unlike :func:`judge` (fixed generic checklist), this generates an
    intent-specific checklist with a strong model when none is supplied, then
    grades each criterion with the local judge. ``q = #YES / #criteria``.

    Args:
        intent: The network intent the response is meant to satisfy.
        response_text: Candidate answer to evaluate.
        checklist: Optional pre-built tuple of verifiable criteria. When None,
            it is generated via ``generate_checklist`` (uses openrouter_client).
        openrouter_client: Optional httpx.Client for checklist generation
            (OpenRouter). Only used when ``checklist`` is None.
        ollama_client: Optional httpx.Client for the local judge (Ollama).

    Returns:
        A JudgeScore with q = (#YES / #criteria) and the per-criterion verdicts
        keyed by the criterion text.

    Raises:
        ChecklistError: when checklist generation yields no criterion.
        OpenRouterError: on checklist-generation request failure.
        JudgeError: Ollama unreachable, non-2xx status, or malformed JSON.
    """
    items = (
        checklist
        if checklist is not None
        else generate_checklist(intent, client=openrouter_client)
    )

    owns_client = ollama_client is None
    active = ollama_client or httpx.Client(timeout=config.OPENROUTER_TIMEOUT_S)
    try:
        verdicts = {
            criterion: _grade_one(intent, response_text, criterion, active)
            for criterion in items
        }
    finally:
        if owns_client:
            active.close()

    q = sum(verdicts.values()) / len(verdicts)
    return JudgeScore(q=q, checklist=verdicts)


# ────────────────────────────────────────────────────────────────────────────
# Pairwise judging (Exp. D)
#
# Independent absolute scoring (judge_rocketeval) under-discriminates: a small
# judge often gives the same score to a correct answer and a one-error variant.
# Pairwise comparison shows BOTH answers at once and asks which is better, which
# is an easier, relative judgement. To cancel the well-known position bias of
# LLM judges, every pairwise call is run TWICE with the order flipped, and a
# winner is declared only when both passes agree on the same real response.
# ────────────────────────────────────────────────────────────────────────────

PairwiseVerdict = str  # one of "A", "B", "tie"

_PAIRWISE_INSTRUCTION = (
    "You are a strict evaluator of network-operations assistant answers. "
    "Two candidate responses to the same network intent are shown below. "
    "Decide which one better satisfies the intent (more correct, complete and "
    "appropriate for the domain). Answer with a single token: A, B, or TIE. "
    "Do not explain."
)

# Match a lone verdict token, tolerating 'Response A', 'A is better', case and
# punctuation. Word boundaries stop matching the 'a' inside ordinary words.
_PICK_A_RE = re.compile(r"\b(?:response\s+)?a\b", re.IGNORECASE)
_PICK_B_RE = re.compile(r"\b(?:response\s+)?b\b", re.IGNORECASE)
_PICK_TIE_RE = re.compile(r"\btie\b|\bequal\b|\bsame\b|\bdraw\b", re.IGNORECASE)


def _build_pairwise_prompt(
    intent: Intent,
    first: str,
    second: str,
    checklist: Optional[tuple[str, ...]],
) -> str:
    """Compose a single prompt comparing two responses for one intent."""
    grid = ""
    if checklist:
        lines = "\n".join(f"- {c}" for c in checklist)
        grid = f"Use these criteria as a reading grid:\n{lines}\n\n"
    return (
        f"{_PAIRWISE_INSTRUCTION}\n\n"
        f"Network intent ({intent.domain}): {intent.text}\n\n"
        f"{grid}"
        f"Response A: {first}\n\n"
        f"Response B: {second}\n\n"
        f"Answer (A, B, or TIE):"
    )


def _parse_pairwise(content: str) -> PairwiseVerdict:
    """Interpret the judge's free text as "A", "B" or "tie".

    A TIE token wins outright. Otherwise the single present side wins; if both
    or neither A/B tokens appear the verdict is unreadable and counts as "tie"
    (logged, never raised).
    """
    if _PICK_TIE_RE.search(content):
        return "tie"
    has_a = bool(_PICK_A_RE.search(content))
    has_b = bool(_PICK_B_RE.search(content))
    if has_a and not has_b:
        return "A"
    if has_b and not has_a:
        return "B"
    logger.warning("Unreadable pairwise verdict (raw=%r) -> tie.", content.strip()[:80])
    return "tie"


def judge_pairwise(
    intent: Intent,
    response_a: str,
    response_b: str,
    *,
    checklist: Optional[tuple[str, ...]] = None,
    ollama_client: Optional[httpx.Client] = None,
) -> PairwiseVerdict:
    """Compare two responses with the local judge, returning "A", "B" or "tie".

    Runs the comparison twice with the presentation order swapped to neutralise
    position bias. ``response_a`` / ``response_b`` keep their caller-facing
    meaning in the returned verdict regardless of the internal swap. A winner is
    declared only when both passes agree on the same real response; otherwise
    (disagreement, an explicit tie, or unreadable output) the verdict is "tie".

    Args:
        intent: The network intent both responses are meant to satisfy.
        response_a: First candidate (returned as "A" when it wins).
        response_b: Second candidate (returned as "B" when it wins).
        checklist: Optional verifiable criteria shown as a reading grid.
        ollama_client: Optional injected httpx.Client (for tests / reuse).

    Returns:
        "A", "B", or "tie".

    Raises:
        JudgeError: Ollama unreachable, non-2xx status, or malformed JSON.
    """
    owns_client = ollama_client is None
    active = ollama_client or httpx.Client(timeout=config.OPENROUTER_TIMEOUT_S)
    try:
        forward = _parse_pairwise(
            _ask_judge(_build_pairwise_prompt(intent, response_a, response_b, checklist), active)
        )
        # Swapped order: response_b is now shown first ("A"), response_a second.
        swapped = _parse_pairwise(
            _ask_judge(_build_pairwise_prompt(intent, response_b, response_a, checklist), active)
        )
    finally:
        if owns_client:
            active.close()

    return _combine_pairwise(forward, swapped)


def _combine_pairwise(forward: PairwiseVerdict, swapped: PairwiseVerdict) -> PairwiseVerdict:
    """Fuse the two ordered verdicts into a position-bias-free decision.

    In the swapped pass the labels are inverted, so a real win for response_a is
    "A" forward and "B" swapped. Both passes must agree on the same real
    response, else the result is "tie".
    """
    a_wins = forward == "A" and swapped == "B"
    b_wins = forward == "B" and swapped == "A"
    if a_wins:
        return "A"
    if b_wins:
        return "B"
    return "tie"
