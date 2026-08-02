"""Verb ``priority``: mark a flow's DSCP class.

Realised as an OpenFlow ToS rewrite in the pipeline's marking stage, which
then resubmits so the forwarding stage still gets to decide where the packet
goes. Marking and routing therefore compose instead of competing: before the
stages existed both sat at priority 150 in the single table, and an intent
asking for a rerouted flow to be marked (c-003) could only ever get one of the
two. See the pipeline scheme in :mod:`bench.verbs.base`.

Verified by capturing the ToS byte at the destination. This checks the
marking, not the scheduling behaviour it is supposed to buy: the bench has no
check for differentiated service under load. The limitation is in the report.
"""
from __future__ import annotations

from app.llm.intent_plan import PriorityOp
from bench.subset import EndpointRef
from bench.verbs.base import (
    PRIORITY_MARK,
    TABLE_MARK,
    TABLE_QUEUE,
    OvsCommand,
    resolve,
)

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
                f"ovs-ofctl add-flow {{switch}} 'table={TABLE_MARK},"
                f"priority={PRIORITY_MARK},dl_type=0x0800,"
                f"dl_src={src.mac},dl_dst={dst.mac},"
                f"actions=mod_nw_tos:{tos},resubmit(,{TABLE_QUEUE})'"
            ),
        ),
    )
