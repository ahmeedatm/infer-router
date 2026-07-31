"""Tests for provider resolution and tier-to-model mapping."""
from __future__ import annotations

import httpx
import pytest

from app import config
from app.cli import providers
from app.llm.pool import PoolModel


def _model(tier: str, model_id: str, domain=None) -> PoolModel:
    return PoolModel(
        model_id=model_id, tier=tier, domain=domain, cost=0.1, latency_ms=100.0
    )


def test_api_provider_uses_calibrated_pool():
    provider = providers.api_provider()
    assert provider.light_model == config.MODEL_LIGHT
    assert provider.heavy_model == config.MODEL_HEAVY
    assert provider.checklist_model == config.CHECKLIST_MODEL


def test_local_provider_uses_the_bench_couple():
    provider = providers.local_provider()
    assert provider.light_model == providers.LOCAL_LIGHT_MODEL
    assert provider.heavy_model == providers.LOCAL_HEAVY_MODEL


def test_local_checklist_generator_differs_from_both_tiers_and_the_judge():
    provider = providers.local_provider()
    others = {provider.light_model, provider.heavy_model, config.JUDGE_MODEL}
    assert provider.checklist_model not in others


def test_resolve_rejects_unknown_provider():
    with pytest.raises(providers.ProviderError, match="Unknown provider"):
        providers.resolve("groq")


def test_resolve_applies_only_the_supplied_overrides():
    provider = providers.resolve("local", heavy_model="qwen2.5:7b-instruct")
    assert provider.heavy_model == "qwen2.5:7b-instruct"
    assert provider.light_model == providers.LOCAL_LIGHT_MODEL


def test_serving_model_id_maps_tier_to_local_stand_in():
    provider = providers.local_provider()
    heavy = _model("heavy", config.MODEL_HEAVY)
    assert providers.serving_model_id(provider, heavy) == providers.LOCAL_HEAVY_MODEL


def test_serving_model_id_drops_the_domain_suffix_on_api():
    provider = providers.api_provider()
    specialist = _model("heavy", f"{config.MODEL_HEAVY}#ran", domain="ran")
    assert providers.serving_model_id(provider, specialist) == config.MODEL_HEAVY


def test_call_routes_an_ollama_tag_to_the_local_backend():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200, json={"message": {"content": "ok"}, "eval_count": 3}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = providers.call("gemma2:2b", "prompt", client=client)
    assert response.text == "ok"
    assert response.cost_estimate == 0.0


def test_call_routes_an_openrouter_id_to_the_api_backend():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "openrouter" in str(request.url)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = providers.call("qwen/qwen-2.5-72b-instruct", "prompt", client=client)
    assert response.text == "ok"
