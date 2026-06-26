"""Thin OpenRouter chat-completions client.

Exposes a single entry point, ``call_model``, that posts a prompt to the
OpenRouter chat-completions endpoint and returns an immutable
``ModelResponse``. Latency is measured client-side. Errors are surfaced
explicitly through ``OpenRouterError`` (never silently swallowed). Transient
failures (timeout, network transport error, HTTP 429/5xx, non-JSON body) are
retried with exponential backoff; definitive 4xx errors are not.

The ``client`` parameter is injectable so tests can pass an httpx.Client
backed by a MockTransport (no real network, no API key required).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

import httpx

from app import config
from app.llm.schema import ModelResponse

# HTTP statuses worth retrying: rate limit + transient gateway/server errors.
# Everything else in the 4xx range (400/401/402/403/404) is definitive.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class OpenRouterError(RuntimeError):
    """Raised for any failure while calling OpenRouter (network, status, parsing)."""


class _TransientError(Exception):
    """Internal signal: the attempt failed in a way that is worth retrying."""


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
    fabricated estimate, surfacing the gap rather than guessing.
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


def _build_body(
    model_id: str,
    prompt: str,
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> dict[str, Any]:
    """Build the chat-completions request body (immutable per call)."""
    body: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def _attempt(
    active: httpx.Client,
    model_id: str,
    body: dict[str, Any],
) -> ModelResponse:
    """Run a single request attempt.

    Raises:
        _TransientError: timeout, network transport error, retryable status
            (429/5xx), or a non-JSON body (gateway hiccup) — worth retrying.
        OpenRouterError: definitive failure (4xx other than 429) — no retry.
    """
    headers = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}
    start = time.perf_counter()
    try:
        response = active.post(_endpoint(), json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise _TransientError(f"OpenRouter request timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise _TransientError(f"OpenRouter request failed: {exc}") from exc
    latency_ms = (time.perf_counter() - start) * 1000.0

    if response.status_code in _RETRYABLE_STATUSES:
        raise _TransientError(
            f"OpenRouter returned status {response.status_code}: "
            f"{response.text[:300]}"
        )
    if response.status_code >= 400:
        raise OpenRouterError(
            f"OpenRouter returned status {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise _TransientError(f"Response is not valid JSON: {exc}") from exc

    return _parse_payload(model_id, payload, latency_ms)


def call_model(
    model_id: str,
    prompt: str,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    client: Optional[httpx.Client] = None,
    max_retries: Optional[int] = None,
    backoff_s: Optional[float] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ModelResponse:
    """Call an OpenRouter model with a single user prompt.

    Retries transient failures only (timeout, network transport error,
    HTTP 429/5xx, or a non-JSON body). Definitive errors (400/401/402/403/404)
    raise ``OpenRouterError`` immediately — retrying them is useless and costly.

    Args:
        model_id: OpenRouter model identifier.
        prompt: User message content.
        temperature: Optional sampling temperature. Forwarded only when
            provided (non-None); otherwise the field is omitted.
        max_tokens: Optional generation budget (completion token cap).
            Forwarded only when provided (non-None); otherwise omitted. Set
            this to avoid truncated answers from models with a low default cap.
        client: Optional injected httpx.Client (for tests / connection reuse).
        max_retries: Extra attempts after the first on transient failures.
            Defaults to ``config.OPENROUTER_MAX_RETRIES``.
        backoff_s: Base for exponential backoff (backoff * 2**attempt).
            Defaults to ``config.OPENROUTER_RETRY_BACKOFF_S``.
        sleep: Injectable sleep function (tests pass a non-blocking stub).

    Returns:
        An immutable ModelResponse with measured latency and token usage.

    Raises:
        OpenRouterError: on a definitive error, or after exhausting all
            attempts on a transient failure.
    """
    if max_retries is None:
        max_retries = config.OPENROUTER_MAX_RETRIES
    if backoff_s is None:
        backoff_s = config.OPENROUTER_RETRY_BACKOFF_S

    owns_client = client is None
    active = client or _build_client()
    body = _build_body(model_id, prompt, temperature, max_tokens)
    total_attempts = max_retries + 1

    try:
        last_error: Optional[_TransientError] = None
        for attempt in range(total_attempts):
            try:
                return _attempt(active, model_id, body)
            except _TransientError as exc:
                last_error = exc
                if attempt < total_attempts - 1:
                    sleep(backoff_s * (2 ** attempt))
        raise OpenRouterError(
            f"OpenRouter call failed after {total_attempts} attempt(s): "
            f"{last_error}"
        ) from last_error
    finally:
        if owns_client:
            active.close()
