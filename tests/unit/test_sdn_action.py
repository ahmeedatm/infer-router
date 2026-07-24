"""Unit tests for app.llm.sdn_action (pure : pas de réseau)."""
from __future__ import annotations

import pytest

from app.llm.sdn_action import (
    SdnAction,
    SdnActionError,
    build_action_prompt,
    parse_action_response,
)


def test_prompt_lists_endpoints_and_actions():
    prompt = build_action_prompt("Block RAN mgmt from core billing", ["ran_mgmt", "core_billing"])
    assert "ran_mgmt" in prompt and "core_billing" in prompt
    assert "block" in prompt and "allow" in prompt and "bandwidth" in prompt


def test_parse_extracts_json_block():
    raw = 'Sure:\n```json\n{"action":"block","src":"ran_mgmt","dst":"core_billing"}\n```'
    action = parse_action_response("sec-001", raw)
    assert action == SdnAction(
        intent_id="sec-001", action="block", src="ran_mgmt", dst="core_billing"
    )


def test_parse_bandwidth_keeps_mbps():
    raw = '{"action":"bandwidth","src":"h1","dst":"h2","bw_mbps":8.0}'
    action = parse_action_response("slice-001", raw)
    assert action.bw_mbps == 8.0


def test_parse_rejects_unknown_action():
    with pytest.raises(SdnActionError):
        parse_action_response("x", '{"action":"drop","src":"a","dst":"b"}')


def test_parse_rejects_non_json():
    with pytest.raises(SdnActionError):
        parse_action_response("x", "no json here")
