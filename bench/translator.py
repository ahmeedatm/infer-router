"""Pure mapping: SdnAction + endpoint table -> ONOS REST command."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.llm.sdn_action import SdnAction
from bench.subset import EndpointRef


class TranslateError(ValueError):
    """Raised when an action cannot be mapped to an ONOS command."""


class OnosCommand(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["host_intent", "acl_deny", "p2p_bw_intent"]
    method: Literal["POST"] = "POST"
    path: str
    payload: dict


def _resolve(endpoints: dict[str, EndpointRef], key: str) -> EndpointRef:
    if key not in endpoints:
        raise TranslateError(f"unknown endpoint {key!r}")
    return endpoints[key]


def translate(
    action: SdnAction,
    endpoints: dict[str, EndpointRef],
    app_id: str = "inferrouter",
) -> OnosCommand:
    src = _resolve(endpoints, action.src)
    dst = _resolve(endpoints, action.dst)

    if action.action == "allow":
        return OnosCommand(
            kind="host_intent",
            path="/onos/v1/intents",
            payload={
                "type": "HostToHostIntent",
                "appId": app_id,
                "priority": 100,
                "one": f"{src.mac}/-1",
                "two": f"{dst.mac}/-1",
            },
        )
    if action.action == "block":
        return OnosCommand(
            kind="acl_deny",
            path="/onos/v1/acl/rules",
            payload={"srcMac": src.mac, "dstMac": dst.mac},
        )
    # bandwidth
    if action.bw_mbps is None:
        raise TranslateError("bandwidth action requires bw_mbps")
    return OnosCommand(
        kind="p2p_bw_intent",
        path="/onos/v1/intents",
        payload={
            "type": "PointToPointIntent",
            "appId": app_id,
            "priority": 200,
            "one": f"{src.mac}/-1",
            "two": f"{dst.mac}/-1",
            "constraints": [
                {"type": "BandwidthConstraint", "bandwidth": action.bw_mbps * 1e6}
            ],
        },
    )
