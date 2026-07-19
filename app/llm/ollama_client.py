"""Local model generation via Ollama (chat endpoint).

Mirrors :mod:`app.llm.openrouter_client`'s ``call_model`` contract so a local
model can stand in for an API tier in experiments: same ``ModelResponse``
shape, measured wall-clock latency, injectable ``httpx.Client`` for tests.

Design notes:
- ``cost_estimate`` is 0.0 by construction: local inference has no per-token
  price. Latency measured here reflects THIS machine (MacBook Air M5), not a
  production edge server; treat it as indicative, not benchmark-grade.
- Ollama being unreachable, or returning a non-2xx / non-JSON / malformed
  payload, raises :class:`OllamaClientError` (hard failure, no silent retry:
  a local server that misbehaves must be fixed, not hammered).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app import config
from app.llm.schema import ModelResponse


class OllamaClientError(Exception):
    """The local Ollama server could not produce a usable completion."""


def _endpoint() -> str:
    """Absolute Ollama chat URL, built from config (never relative)."""
    return f"{config.OLLAMA_HOST.rstrip('/')}/api/chat"


def _parse_payload(model_id: str, payload: Any, latency_ms: float) -> ModelResponse:
    """Map an Ollama /api/chat payload onto the shared ModelResponse schema."""
    try:
        text = payload["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise OllamaClientError(
            f"Ollama payload for '{model_id}' lacks message.content: {payload!r:.200}"
        ) from exc
    if not isinstance(text, str) or not text.strip():
        raise OllamaClientError(f"Ollama returned an empty completion for '{model_id}'.")
    return ModelResponse(
        model_id=model_id,
        text=text,
        latency_ms=latency_ms,
        prompt_tokens=int(payload.get("prompt_eval_count", 0)),
        completion_tokens=int(payload.get("eval_count", 0)),
        cost_estimate=0.0,
    )


def call_model(
    model_id: str,
    prompt: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = config.RESPONSE_MAX_TOKENS,
    client: Optional[httpx.Client] = None,
) -> ModelResponse:
    """Run one non-streaming completion on the local Ollama server.

    Args:
        model_id: Ollama model tag (e.g. ``qwen2.5:7b-instruct``).
        prompt: Full user prompt (system framing included by the caller).
        temperature: Sampling temperature; 0.0 for reproducible runs.
        max_tokens: Generation cap, mapped to Ollama's ``num_predict``.
        client: Optional injected httpx.Client (tests use MockTransport).

    Returns:
        A ModelResponse with measured latency and token counts.

    Raises:
        OllamaClientError: on connection failure, non-2xx status, non-JSON
            body, or a payload without usable text.
    """
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    active = client or httpx.Client(timeout=config.OLLAMA_GENERATION_TIMEOUT_S)
    start = time.perf_counter()
    try:
        response = active.post(_endpoint(), json=body)
    except httpx.HTTPError as exc:
        raise OllamaClientError(f"Ollama unreachable at {_endpoint()}: {exc}") from exc
    finally:
        if client is None:
            active.close()
    latency_ms = (time.perf_counter() - start) * 1000.0

    if response.status_code // 100 != 2:
        raise OllamaClientError(
            f"Ollama returned HTTP {response.status_code} for '{model_id}': "
            f"{response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OllamaClientError(
            f"Ollama returned a non-JSON body for '{model_id}'."
        ) from exc
    return _parse_payload(model_id, payload, latency_ms)
