from __future__ import annotations

import pytest

from app.llm.sdn_action import SdnAction
from bench.subset import EndpointRef
from bench.translator import FlowSpec, TranslateError, translate

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_allow_is_noop():
    spec = translate(SdnAction(intent_id="r", action="allow", src="a", dst="b"), EP)
    assert isinstance(spec, FlowSpec)
    assert spec.kind == "allow"
    assert spec.drop_pairs == ()


def test_block_drops_both_directions():
    spec = translate(SdnAction(intent_id="s", action="block", src="a", dst="b"), EP)
    assert spec.kind == "block"
    assert spec.drop_pairs == (
        ("00:00:00:00:00:01", "00:00:00:00:00:03"),
        ("00:00:00:00:00:03", "00:00:00:00:00:01"),
    )


def test_bandwidth_sets_policing():
    spec = translate(
        SdnAction(intent_id="q", action="bandwidth", src="a", dst="b", bw_mbps=8.0), EP
    )
    assert spec.kind == "qos"
    assert spec.policing_kbps == 8000
    assert spec.policing_host == "h1"


def test_bandwidth_requires_mbps():
    with pytest.raises(TranslateError):
        translate(SdnAction(intent_id="q", action="bandwidth", src="a", dst="b"), EP)


def test_unknown_endpoint_raises():
    with pytest.raises(TranslateError):
        translate(SdnAction(intent_id="x", action="allow", src="a", dst="ghost"), EP)
