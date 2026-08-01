"""Verbs ``allow`` and ``block``.

Without a selector, ``block`` drops both directions by MAC pair at priority
200, and ``allow`` is a no-op: base L2 connectivity is already installed by the
topology. With an L4 selector, both act at priority 300 on the narrowed flow
only, ``block`` dropping it and ``allow`` punching a hole through a broader
drop.

The selected ``allow`` is emitted in both directions (``tp_dst`` forward,
``tp_src`` back). A hole punched one way is not a hole: the forward SYN gets
through at 300 and the SYN-ACK falls back into the 200 drop, so the connection
never establishes and the permission is unobservable.
"""
from __future__ import annotations

from typing import Union

from app.llm.intent_plan import AllowOp, BlockOp, Selector
from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, resolve

OP_MODEL = (AllowOp, BlockOp)

_PROTO_NUM = {"icmp": 1, "tcp": 6, "udp": 17}


def _match(dl_src: str, dl_dst: str, selector: Selector,
           port_field: str = "tp_dst") -> str:
    parts = [f"dl_src={dl_src}", f"dl_dst={dl_dst}", "dl_type=0x0800"]
    if selector.proto is not None:
        parts.append(f"nw_proto={_PROTO_NUM[selector.proto]}")
    if selector.port is not None:
        parts.append(f"{port_field}={selector.port}")
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
        if op.verb == "block":
            # Dropping the forward direction is enough to kill the flow, and
            # a reverse drop would also cut the return traffic of permitted
            # flows that happen to use the port as a source.
            return (_flow(_match(src.mac, dst.mac, op.selector), 300, "drop"),)
        # A permission has to cover the return path or it establishes
        # nothing: the SYN passes at 300 and the SYN-ACK falls back into the
        # broader drop at 200. Measured in the VM as "tcp connect failed:
        # Connection timed out" with the forward rule alone.
        return (
            _flow(_match(src.mac, dst.mac, op.selector), 300, "normal"),
            _flow(_match(dst.mac, src.mac, op.selector, "tp_src"), 300, "normal"),
        )

    if op.verb == "allow":
        return ()

    return (
        _flow(f"dl_src={src.mac},dl_dst={dst.mac}", 200, "drop"),
        _flow(f"dl_src={dst.mac},dl_dst={src.mac}", 200, "drop"),
    )
