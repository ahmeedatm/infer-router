"""Which concrete models serve a routing decision, and how they are called.

The routing decision itself is always taken on the calibrated pool profiles
(``app.config``), so the CLI shows the same arbitration as the published
benchmark. Execution is another matter: the API pool costs OpenRouter credits,
so a local provider maps each tier onto the Ollama couple used by the
real-network bench (gemma2:2b / qwen2.5:14b-instruct). The chosen tier is
preserved; only the model serving it changes.
"""
from __future__ import annotations

from typing import Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict

from app import config
from app.llm.ollama_client import call_model as call_local_model
from app.llm.openrouter_client import call_model as call_api_model
from app.llm.pool import PoolModel
from app.llm.prompting import base_model_id, is_local_model_id
from app.llm.schema import ModelResponse

ProviderName = Literal["api", "local"]

# Ollama stand-ins for the two tiers, identical to the couple used by the
# real-network validation bench so both experiments stay comparable.
LOCAL_LIGHT_MODEL = "gemma2:2b"
LOCAL_HEAVY_MODEL = "qwen2.5:14b-instruct"
# Third local model for checklist generation: distinct from both pool tiers and
# from the judge (gemma2:9b), to keep the evaluator neutral towards what it
# grades. Weaker than the API generator (claude-sonnet-4.6) — a documented
# degradation, not an equivalent.
LOCAL_CHECKLIST_MODEL = "qwen2.5:7b-instruct"


class ProviderError(RuntimeError):
    """Raised when a provider cannot be resolved from its name."""


class Provider(BaseModel):
    """Immutable mapping from pool tiers to the models actually called.

    Attributes:
        name: ``api`` (OpenRouter, billed) or ``local`` (Ollama, free).
        light_model: Model serving the light tier.
        heavy_model: Model serving the heavy tier.
        checklist_model: Model generating the RocketEval checklist.
    """

    model_config = ConfigDict(frozen=True)

    name: ProviderName
    light_model: str
    heavy_model: str
    checklist_model: str


def api_provider() -> Provider:
    """The calibrated API pool: qwen-2.5-72b / claude-opus-4.8, Sonnet judgeur."""
    return Provider(
        name="api",
        light_model=config.MODEL_LIGHT,
        heavy_model=config.MODEL_HEAVY,
        checklist_model=config.CHECKLIST_MODEL,
    )


def local_provider() -> Provider:
    """The free Ollama stand-in couple used by the real-network bench."""
    return Provider(
        name="local",
        light_model=LOCAL_LIGHT_MODEL,
        heavy_model=LOCAL_HEAVY_MODEL,
        checklist_model=LOCAL_CHECKLIST_MODEL,
    )


def resolve(
    name: str,
    *,
    light_model: Optional[str] = None,
    heavy_model: Optional[str] = None,
    checklist_model: Optional[str] = None,
) -> Provider:
    """Build a provider from its name, with optional per-model overrides.

    Args:
        name: ``api`` or ``local``.
        light_model: Overrides the model serving the light tier.
        heavy_model: Overrides the model serving the heavy tier.
        checklist_model: Overrides the checklist generator.

    Returns:
        An immutable :class:`Provider`.

    Raises:
        ProviderError: when ``name`` is neither ``api`` nor ``local``.
    """
    if name == "api":
        base = api_provider()
    elif name == "local":
        base = local_provider()
    else:
        raise ProviderError(f"Unknown provider {name!r}; expected 'api' or 'local'.")
    return base.model_copy(
        update={
            key: value
            for key, value in (
                ("light_model", light_model),
                ("heavy_model", heavy_model),
                ("checklist_model", checklist_model),
            )
            if value is not None
        }
    )


def serving_model_id(provider: Provider, chosen: PoolModel) -> str:
    """Return the model that actually serves ``chosen``'s tier under ``provider``.

    The domain suffix of a specialist is dropped: no specialist has ever been
    built, so it is served by its heavy base model.
    """
    if provider.name == "api":
        return base_model_id(chosen.model_id)
    return provider.light_model if chosen.tier == "light" else provider.heavy_model


def call(
    model_id: str,
    prompt: str,
    *,
    max_tokens: int = config.RESPONSE_MAX_TOKENS,
    client: Optional[httpx.Client] = None,
) -> ModelResponse:
    """Run one completion, dispatching on the model-id convention.

    Args:
        model_id: OpenRouter id (``vendor/model``) or Ollama tag (``name:tag``).
        prompt: Full prompt to send.
        max_tokens: Generation cap.
        client: Optional injected httpx.Client (tests use MockTransport).

    Returns:
        The :class:`ModelResponse` with measured latency and token counts.

    Raises:
        OpenRouterError / OllamaClientError: propagated from the backend.
    """
    backend = call_local_model if is_local_model_id(model_id) else call_api_model
    return backend(
        model_id, prompt, temperature=0.0, max_tokens=max_tokens, client=client
    )
