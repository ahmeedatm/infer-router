from __future__ import annotations

import pytest

from app.llm.sdn_action import SdnAction
from bench.subset import EndpointRef
from bench.translator import OnosCommand, TranslateError, translate

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_allow_maps_to_host_intent():
    cmd = translate(SdnAction(intent_id="r", action="allow", src="a", dst="b"), EP)
    assert cmd.kind == "host_intent"
    assert cmd.path == "/onos/v1/intents"
    assert cmd.payload["type"] == "HostToHostIntent"
    assert cmd.payload["one"].startswith("00:00:00:00:00:01")
    assert cmd.payload["two"].startswith("00:00:00:00:00:03")


def test_block_maps_to_acl_deny():
    cmd = translate(SdnAction(intent_id="s", action="block", src="a", dst="b"), EP)
    assert cmd.kind == "acl_deny"
    assert cmd.path == "/onos/v1/acl/rules"
    assert cmd.payload["srcMac"] == "00:00:00:00:00:01"
    assert cmd.payload["dstMac"] == "00:00:00:00:00:03"


def test_bandwidth_requires_mbps():
    with pytest.raises(TranslateError):
        translate(SdnAction(intent_id="q", action="bandwidth", src="a", dst="b"), EP)


def test_unknown_endpoint_raises():
    with pytest.raises(TranslateError):
        translate(SdnAction(intent_id="x", action="allow", src="a", dst="ghost"), EP)
