from __future__ import annotations

import httpx
import pytest

from bench.onos_client import OnosClient, OnosError
from bench.translator import OnosCommand


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://onos")


def test_execute_posts_payload_and_returns_location():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(201, headers={"Location": "/onos/v1/intents/app/key1"})

    onos = OnosClient("http://onos", client=_client(handler))
    cmd = OnosCommand(kind="acl_deny", path="/onos/v1/acl/rules",
                      payload={"srcMac": "a", "dstMac": "b"})
    loc = onos.execute(cmd)
    assert loc == "/onos/v1/intents/app/key1"
    assert seen["url"].endswith("/onos/v1/acl/rules")


def test_execute_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad")

    onos = OnosClient("http://onos", client=_client(handler))
    cmd = OnosCommand(kind="acl_deny", path="/onos/v1/acl/rules", payload={})
    with pytest.raises(OnosError):
        onos.execute(cmd)


def test_wait_flows_installed_polls_until_count():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        flows = [] if calls["n"] < 2 else [{"id": "1"}, {"id": "2"}]
        return httpx.Response(200, json={"flows": flows})

    onos = OnosClient("http://onos", client=_client(handler))
    assert onos.wait_flows_installed(2, timeout_s=5.0, poll_s=0.0, sleep=lambda s: None) is True
