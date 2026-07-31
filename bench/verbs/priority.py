"""Verb ``priority``: mark a flow's DSCP class.

Realised as an OpenFlow ToS rewrite on the matched flow. Verified by capturing
the ToS byte at the destination. This checks the marking, not the behaviour
under load: testing scheduling under congestion would duplicate what
``bandwidth_min`` already measures. The limitation is documented in the report.
"""
from __future__ import annotations

from app.llm.intent_plan import PriorityOp
from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, resolve

OP_MODEL = PriorityOp

# ToS byte = DSCP << 2. EF (46) -> 184, CS1 (8) -> 32, best effort -> 0.
TOS_BY_CLASS = {"high": 184, "normal": 0, "low": 32}


def to_commands(
    op: PriorityOp,
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    src = resolve(endpoints, op.src)
    dst = resolve(endpoints, op.dst)
    tos = TOS_BY_CLASS[op.klass]
    return (
        OvsCommand(
            target="all",
            command=(
                f"ovs-ofctl add-flow {{switch}} 'priority=150,dl_type=0x0800,"
                f"dl_src={src.mac},dl_dst={dst.mac},"
                f"actions=mod_nw_tos:{tos},normal'"
            ),
        ),
    )
