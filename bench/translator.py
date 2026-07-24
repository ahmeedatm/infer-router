"""Pure mapping: SdnAction + endpoint table -> OVS flow specification.

No SDN controller: the action is realised directly on Open vSwitch. This module
stays pure (no execution); the runner applies the FlowSpec via ovs-ofctl /
ovs-vsctl. Three kinds:
    allow -> nothing (default L2 connectivity in standalone mode)
    block -> bidirectional drop flow-mods (by source/dest MAC)
    qos   -> ingress rate policing (kbps) on the source host's switch port
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.llm.sdn_action import SdnAction
from bench.subset import EndpointRef


class TranslateError(ValueError):
    """Raised when an action cannot be mapped to a flow specification."""


class FlowSpec(BaseModel):
    """Immutable OVS realisation of a network action."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["allow", "block", "qos"]
    # (dl_src, dl_dst) MAC pairs to drop (both directions for isolation).
    drop_pairs: tuple[tuple[str, str], ...] = ()
    # Ingress policing rate applied to policing_host's switch port.
    policing_kbps: Optional[int] = None
    policing_host: Optional[str] = None


def _resolve(endpoints: dict[str, EndpointRef], key: str) -> EndpointRef:
    if key not in endpoints:
        raise TranslateError(f"unknown endpoint {key!r}")
    return endpoints[key]


def translate(action: SdnAction, endpoints: dict[str, EndpointRef]) -> FlowSpec:
    src = _resolve(endpoints, action.src)
    dst = _resolve(endpoints, action.dst)

    if action.action == "allow":
        return FlowSpec(kind="allow")
    if action.action == "block":
        return FlowSpec(
            kind="block",
            drop_pairs=((src.mac, dst.mac), (dst.mac, src.mac)),
        )
    # bandwidth -> ingress policing cap on the source host
    if action.bw_mbps is None:
        raise TranslateError("bandwidth action requires bw_mbps")
    return FlowSpec(
        kind="qos",
        policing_kbps=int(action.bw_mbps * 1000),
        policing_host=src.host,
    )
