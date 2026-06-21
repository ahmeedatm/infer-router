"""Unit tests for app.llm.openrouter_client (httpx mocked, no real network)."""
import json

import httpx
import pytest

from app.llm.openrouter_client import OpenRouterError, call_model


def _make_client(handler) -> httpx.Client:
    """Build an httpx.Client backed by a MockTransport (no real network)."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_payload(text: str = "Cell 42 load is 73%.") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 18, "completion_tokens": 9},
    }


class TestCallModelNominal:
    def test_returns_model_response(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            resp = call_model(
                "meta-llama/llama-3.2-3b-instruct",
                "Show the load on cell 42.",
                client=client,
            )

        assert resp.model_id == "meta-llama/llama-3.2-3b-instruct"
        assert resp.text == "Cell 42 load is 73%."
        assert resp.prompt_tokens == 18
        assert resp.completion_tokens == 9
        assert resp.latency_ms > 0
        assert resp.cost_estimate > 0  # known model -> priced
        assert captured["url"].endswith("/chat/completions")
        assert captured["auth"].startswith("Bearer ")

    def test_unknown_model_costs_zero(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            resp = call_model("some/unknown-model", "hello", client=client)

        assert resp.cost_estimate == 0.0


class TestCallModelTemperature:
    def test_temperature_included_when_provided(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            call_model("m", "p", temperature=0.0, client=client)

        assert captured["body"]["temperature"] == 0.0

    def test_temperature_absent_when_not_provided(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            call_model("m", "p", client=client)

        assert "temperature" not in captured["body"]


class TestCallModelMaxTokens:
    def test_max_tokens_included_when_provided(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            call_model("m", "p", max_tokens=1024, client=client)

        assert captured["body"]["max_tokens"] == 1024

    def test_max_tokens_absent_when_not_provided(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            call_model("m", "p", client=client)

        assert "max_tokens" not in captured["body"]


class TestCallModelErrors:
    def test_timeout_raises_openrouter_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client)
        assert "timeout" in str(exc.value).lower()

    def test_status_429_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client)
        assert "429" in str(exc.value)

    def test_status_500_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client)
        assert "500" in str(exc.value)

    def test_malformed_json_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json at all")

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError):
                call_model("m", "p", client=client)

    def test_missing_choices_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"usage": {}})

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError):
                call_model("m", "p", client=client)


class TestCallModelUsageHandling:
    def test_missing_usage_defaults_tokens_to_zero(self):
        """Choice present but no usage block -> tokens fall back to 0, cost 0."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
            )

        with _make_client(handler) as client:
            resp = call_model(
                "meta-llama/llama-3.2-3b-instruct", "p", client=client
            )

        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0
        assert resp.cost_estimate == 0.0
