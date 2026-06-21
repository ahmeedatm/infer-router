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


def _no_sleep(_seconds: float) -> None:
    """Sleep stub: tests never block on backoff."""
    return None


class TestCallModelErrors:
    def test_timeout_raises_openrouter_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client, max_retries=0, sleep=_no_sleep)
        assert "timeout" in str(exc.value).lower()

    def test_status_429_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client, max_retries=0, sleep=_no_sleep)
        assert "429" in str(exc.value)

    def test_status_500_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client, max_retries=0, sleep=_no_sleep)
        assert "500" in str(exc.value)

    def test_malformed_json_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json at all")

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError):
                call_model("m", "p", client=client, max_retries=0, sleep=_no_sleep)

    def test_missing_choices_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"usage": {}})

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError):
                call_model("m", "p", client=client, max_retries=0, sleep=_no_sleep)


class TestCallModelRetry:
    def test_503_then_200_succeeds_after_retry(self):
        calls = {"n": 0}
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="service unavailable")
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            resp = call_model(
                "meta-llama/llama-3.2-3b-instruct",
                "p",
                client=client,
                max_retries=3,
                sleep=sleeps.append,
            )

        assert resp.text == "Cell 42 load is 73%."
        assert calls["n"] == 2  # one failure, one success
        assert sleeps == [pytest.approx(2.0)]  # one backoff before the retry

    def test_non_json_then_200_succeeds_after_retry(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, text="<html>gateway hiccup</html>")
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            resp = call_model(
                "meta-llama/llama-3.2-3b-instruct",
                "p",
                client=client,
                max_retries=3,
                sleep=_no_sleep,
            )

        assert resp.text == "Cell 42 load is 73%."
        assert calls["n"] == 2

    def test_timeout_then_200_succeeds_after_retry(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.TimeoutException("timed out", request=request)
            return httpx.Response(200, json=_ok_payload())

        with _make_client(handler) as client:
            resp = call_model(
                "meta-llama/llama-3.2-3b-instruct",
                "p",
                client=client,
                max_retries=3,
                sleep=_no_sleep,
            )

        assert resp.text == "Cell 42 load is 73%."
        assert calls["n"] == 2

    def test_402_raises_immediately_without_retry(self):
        calls = {"n": 0}
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(402, json={"error": "insufficient credits"})

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model(
                    "m", "p", client=client, max_retries=3, sleep=sleeps.append
                )

        assert "402" in str(exc.value)
        assert calls["n"] == 1  # no retry on a definitive error
        assert sleeps == []  # never slept

    def test_persistent_503_raises_after_n_attempts(self):
        calls = {"n": 0}
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, text="still down")

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model(
                    "m", "p", client=client, max_retries=3, sleep=sleeps.append
                )

        message = str(exc.value)
        assert "503" in message
        assert "4" in message  # 1 initial + 3 retries = 4 attempts
        assert calls["n"] == 4
        # Exponential backoff between attempts: 2s, 4s, 8s.
        assert sleeps == [
            pytest.approx(2.0),
            pytest.approx(4.0),
            pytest.approx(8.0),
        ]

    def test_400_raises_immediately_without_retry(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400, json={"error": "bad request"})

        with _make_client(handler) as client:
            with pytest.raises(OpenRouterError) as exc:
                call_model("m", "p", client=client, max_retries=3, sleep=_no_sleep)

        assert "400" in str(exc.value)
        assert calls["n"] == 1


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
