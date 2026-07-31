"""Verb ``reroute``: pin a flow onto one of the two diamond paths.

The topology installs a default path through s2. This verb overrides the
forwarding decision on the two edge switches (s1 and s4) so the flow takes the
requested middle switch instead, in both directions. Verified by reading
per-flow packet counters on both paths.
"""
from __future__ import annotations

from app.llm.intent_plan import RerouteOp
from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, VerbError, resolve

OP_MODEL = RerouteOp

VALID_VIA = frozenset({"s2", "s3"})

_EDGES = ("s1", "s4")


def to_commands(
    op: RerouteOp,
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    src = resolve(endpoints, op.src)
    dst = resolve(endpoints, op.dst)
    if op.via not in VALID_VIA:
        raise VerbError(
            f"{op.via!r} is not a path switch; expected one of {sorted(VALID_VIA)}"
        )
    forward = OvsCommand(
        target="s1",
        command=(
            f"ovs-ofctl add-flow s1 'priority=150,dl_src={src.mac},dl_dst={dst.mac},"
            f"actions=output:{{swport_to:{op.via}}}'"
        ),
    )
    backward = OvsCommand(
        target="s4",
        command=(
            f"ovs-ofctl add-flow s4 'priority=150,dl_src={dst.mac},dl_dst={src.mac},"
            f"actions=output:{{swport_to:{op.via}}}'"
        ),
    )
    return (forward, backward)
