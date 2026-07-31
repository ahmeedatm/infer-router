"""Verbs ``allow`` and ``block``.

Without a selector, ``block`` drops both directions by MAC pair at priority
200, and ``allow`` is a no-op: base L2 connectivity is already installed by the
topology. With an L4 selector, both act at priority 300 on the narrowed flow
only, ``block`` dropping it and ``allow`` punching a hole through a broader
drop.
"""
from __future__ import annotations

from typing import Union

from app.llm.intent_plan import AllowOp, BlockOp, Selector
from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, resolve

OP_MODEL = (AllowOp, BlockOp)

_PROTO_NUM = {"icmp": 1, "tcp": 6, "udp": 17}


def _match(dl_src: str, dl_dst: str, selector: Selector) -> str:
    parts = [f"dl_src={dl_src}", f"dl_dst={dl_dst}", "dl_type=0x0800"]
    if selector.proto is not None:
        parts.append(f"nw_proto={_PROTO_NUM[selector.proto]}")
    if selector.port is not None:
        parts.append(f"tp_dst={selector.port}")
    return ",".join(parts)


def _flow(match: str, priority: int, action: str) -> OvsCommand:
    return OvsCommand(
        target="all",
        command=f"ovs-ofctl add-flow {{switch}} 'priority={priority},{match},actions={action}'",
    )


def to_commands(
    op: Union[AllowOp, BlockOp],
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    src = resolve(endpoints, op.src)
    dst = resolve(endpoints, op.dst)

    if op.selector is not None:
        action = "drop" if op.verb == "block" else "normal"
        return (_flow(_match(src.mac, dst.mac, op.selector), 300, action),)

    if op.verb == "allow":
        return ()

    return (
        _flow(f"dl_src={src.mac},dl_dst={dst.mac}", 200, "drop"),
        _flow(f"dl_src={dst.mac},dl_dst={src.mac}", 200, "drop"),
    )
