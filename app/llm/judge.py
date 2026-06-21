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


def _grade_one(intent: Intent, response_text: str, criterion: str, client: httpx.Client) -> bool:
    """Ask the judge to grade one criterion. Unreadable output -> NO (logged).

    Raises JudgeError only for hard failures (network, status, bad JSON),
    which must abort the whole evaluation rather than be silently scored NO.
    """
    body = {
        "model": config.JUDGE_MODEL,
        "messages": [{"role": "user", "content": _build_prompt(intent, response_text, criterion)}],
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

    content = _extract_content(payload)
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
