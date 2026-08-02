"""Verb ``mirror``: duplicate a host's traffic to a probe port (SPAN).

Realised with an OVS mirror on the bridge holding the source port, which is how
an operator taps traffic towards an IDS. Verified by counting packets captured
on the probe host.
"""
from __future__ import annotations

from app.llm.intent_plan import MirrorOp
from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, resolve

OP_MODEL = MirrorOp


def to_commands(
    op: MirrorOp,
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    src = resolve(endpoints, op.src)
    resolve(endpoints, op.dst)
    probe = resolve(endpoints, op.to)
    return (
        OvsCommand(
            target="all",
            command=(
                "ovs-vsctl -- set bridge {switch} mirrors=@m "
                f"-- --id=@srcport get port {{swport:{src.host}}} "
                f"-- --id=@outport get port {{swport:{probe.host}}} "
                "-- --id=@m create mirror name=intentmirror "
                "select-src-port=@srcport select-dst-port=@srcport "
                "output-port=@outport"
            ),
        ),
    )
