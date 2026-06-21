"""Live smoke test for the LLM-Judge against a real local Ollama.

Skipped automatically when Ollama is not reachable. This is the first
signal for risk H-A: if the judge cannot rank a good answer above an
obviously bad one on a trivial intent, that is a reliability red flag to
escalate.
"""
from __future__ import annotations

import httpx
import pytest

from app import config
from app.llm.judge import judge
from app.llm.schema import Intent


def _ollama_available() -> bool:
    """Ping Ollama's tags endpoint; return False on any failure."""
    try:
        resp = httpx.get(f"{config.OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not reachable at config.OLLAMA_HOST — skipping live judge smoke test.",
)


def _intent() -> Intent:
    return Intent(
        id="ran-read-throughput",
        text="What is the current downlink throughput on cell gNB-042?",
        domain="ran",
        expected_complexity="simple",
        criticality="low",
    )


def test_good_answer_scores_higher_than_bad_answer():
    intent = _intent()
    good = (
        "The current downlink throughput on cell gNB-042 is 142 Mbps, "
        "measured over the last 60-second window."
    )
    bad = "The capital of France is Paris and the weather is sunny today."

    q_good = judge(intent, good).q
    q_bad = judge(intent, bad).q

    print(f"\n[SMOKE] q_good={q_good:.3f}  q_bad={q_bad:.3f}  (model={config.JUDGE_MODEL})")
    assert q_good > q_bad, (
        f"Judge failed to rank a trivial case: q_good={q_good} <= q_bad={q_bad}. "
        "Escalate as H-A reliability concern."
    )
