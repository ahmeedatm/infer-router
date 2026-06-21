"""Thin OpenRouter chat-completions client.

Exposes a single entry point, ``call_model``, that posts a prompt to the
OpenRouter chat-completions endpoint and returns an immutable
``ModelResponse``. Latency is measured client-side. Errors are surfaced
explicitly through ``OpenRouterError`` (never silently swallowed).

The ``client`` parameter is injectable so tests can pass an httpx.Client
backed by a MockTransport (no real network, no API key required).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app import config
from app.llm.schema import ModelResponse


class OpenRouterError(RuntimeError):
    """Raised for any failure while calling OpenRouter (network, status, parsing)."""


def _build_client() -> httpx.Client:
    """Default client used when the caller does not inject one."""
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    return httpx.Client(
        headers=headers,
        timeout=config.OPENROUTER_TIMEOUT_S,
    )


def _endpoint() -> str:
    """Absolute chat-completions URL (built from config, never relative)."""
    return f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"


def _estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from the config pricing grid.

    Unknown models return 0.0 by design: we prefer an explicit 0.0 over a
    fabricated estimate. The spike surfaces this rather than guessing.
    """
    pricing = config.MODEL_PRICING_USD_PER_1K.get(model_id)
    if pricing is None:
        return 0.0
    prompt_cost = (prompt_tokens / 1000.0) * pricing["prompt"]
    completion_cost = (completion_tokens / 1000.0) * pricing["completion"]
    return prompt_cost + completion_cost


def _parse_payload(model_id: str, payload: Any, latency_ms: float) -> ModelResponse:
    """Validate and map an OpenRouter JSON payload to a ModelResponse."""
    if not isinstance(payload, dict):
        raise OpenRouterError("Unexpected response payload (not a JSON object).")

    choices = payload.get("choices")
    if not choices:
        raise OpenRouterError("Response is missing 'choices'.")

    try:
        text = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Malformed 'choices' in response: {exc}") from exc

    # Usage may be absent (e.g. some providers / errors). Default to 0 tokens,
    # which yields a 0.0 cost estimate — documented fallback, no silent failure.
    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)

    return ModelResponse(
        model_id=model_id,
        text=text,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=_estimate_cost(model_id, prompt_tokens, completion_tokens),
    )


def call_model(
    model_id: str,
    prompt: str,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    client: Optional[httpx.Client] = None,
) -> ModelResponse:
    """Call an OpenRouter model with a single user prompt.

    Args:
        model_id: OpenRouter model identifier.
        prompt: User message content.
        temperature: Optional sampling temperature. Forwarded to OpenRouter
            only when provided (non-None); otherwise the provider default is
            used and the field is omitted from the request body.
        max_tokens: Optional generation budget (completion token cap).
            Forwarded to OpenRouter only when provided (non-None); otherwise
            the provider default is used and the field is omitted from the
            request body. Set this to avoid truncated answers from models
            with a low default completion cap.
        client: Optional injected httpx.Client (for tests / connection reuse).

    Returns:
        An immutable ModelResponse with measured latency and token usage.

    Raises:
        OpenRouterError: on timeout, non-2xx status, or malformed response.
    """
    owns_client = client is None
    active = client or _build_client()
    body: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}

    start = time.perf_counter()
    try:
        response = active.post(_endpoint(), json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise OpenRouterError(f"OpenRouter request timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc
    finally:
        if owns_client:
            active.close()
    latency_ms = (time.perf_counter() - start) * 1000.0

    if response.status_code >= 400:
        raise OpenRouterError(
            f"OpenRouter returned status {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenRouterError(f"Response is not valid JSON: {exc}") from exc

    return _parse_payload(model_id, payload, latency_ms)
