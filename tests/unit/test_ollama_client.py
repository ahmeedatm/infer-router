"""Tests du client de génération locale Ollama (MockTransport, zéro réseau).

Contrat de call_model :
- payload nominal -> ModelResponse (texte, latence mesurée, tokens, coût 0.0),
- HTTP non-2xx, corps non-JSON, payload sans texte, texte vide, serveur
  injoignable -> OllamaClientError.
"""
import httpx
import pytest

from app.llm.ollama_client import OllamaClientError, call_model


def _client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_payload(text="Configure the AMF pool as follows.", prompt_n=42, out_n=128):
    return {
        "model": "qwen2.5:7b-instruct",
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": prompt_n,
        "eval_count": out_n,
        "done": True,
    }


class TestCallModelNominal:
    def test_maps_payload_onto_model_response(self):
        client = _client_returning(
            lambda request: httpx.Response(200, json=_ok_payload())
        )
        resp = call_model("qwen2.5:7b-instruct", "intent text", client=client)
        assert resp.model_id == "qwen2.5:7b-instruct"
        assert resp.text.startswith("Configure the AMF")
        assert resp.prompt_tokens == 42
        assert resp.completion_tokens == 128
        assert resp.cost_estimate == 0.0
        assert resp.latency_ms >= 0.0

    def test_sends_prompt_and_generation_options(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_ok_payload())

        client = _client_returning(handler)
        call_model("m", "the prompt", temperature=0.0, max_tokens=99, client=client)
        assert seen["messages"] == [{"role": "user", "content": "the prompt"}]
        assert seen["stream"] is False
        assert seen["options"] == {"temperature": 0.0, "num_predict": 99}


class TestCallModelErrors:
    def test_non_2xx_raises(self):
        client = _client_returning(
            lambda request: httpx.Response(500, text="boom")
        )
        with pytest.raises(OllamaClientError, match="HTTP 500"):
            call_model("m", "p", client=client)

    def test_non_json_body_raises(self):
        client = _client_returning(
            lambda request: httpx.Response(200, text="not json")
        )
        with pytest.raises(OllamaClientError, match="non-JSON"):
            call_model("m", "p", client=client)

    def test_payload_without_text_raises(self):
        client = _client_returning(
            lambda request: httpx.Response(200, json={"done": True})
        )
        with pytest.raises(OllamaClientError, match="message.content"):
            call_model("m", "p", client=client)

    def test_empty_completion_raises(self):
        client = _client_returning(
            lambda request: httpx.Response(200, json=_ok_payload(text="   "))
        )
        with pytest.raises(OllamaClientError, match="empty completion"):
            call_model("m", "p", client=client)

    def test_unreachable_server_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = _client_returning(handler)
        with pytest.raises(OllamaClientError, match="unreachable"):
            call_model("m", "p", client=client)
