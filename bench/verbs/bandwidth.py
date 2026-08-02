"""Verbs ``bandwidth_max`` and ``bandwidth_min``.

``bandwidth_max`` caps a flow with OVS ingress policing on the switch port
facing the source. It is measured, by the ``throughput_max`` check.

``bandwidth_min`` is NOT MEASURED. No check in ``bench/subset.yaml`` observes
it, so it can neither pass nor fail, and "it never fails" must not be read as
"it is correct". It is kept because the verb is part of the vocabulary the
prompt offers: a model may legitimately emit it for an intent asking for a
guaranteed rate, and the parser and translator have to accept it instead of
scoring that model as having produced an unusable plan. What was retired is
the bench's claim to verify the resulting guarantee.

Why: the floor is realised as a linux-htb queue on the switch port facing the
source, whose egress runs back toward the source host rather than along the
flow. The contention the check created happened on the s2-s4 core link, where
no queue was ever installed, so the guarantee could not affect the
measurement, and the check failed under the positive control on all six of
its intents. Putting the queue on the bottleneck port instead would require
the verb to know the topology, which is exactly the property that keeps verb
modules interchangeable. That price was judged too high for one verb.

The queue steering nevertheless sits in the pipeline's own queueing stage
(see :mod:`bench.verbs.base`) rather than competing with forwarding rules in
one flat table. An unmeasured verb that silently broke a measured one would
be the worst of both.
"""
from __future__ import annotations

from typing import Union

from app.llm.intent_plan import BandwidthMaxOp, BandwidthMinOp
from bench.subset import EndpointRef
from bench.verbs.base import (
    PRIORITY_QUEUE,
    TABLE_FORWARD,
    TABLE_QUEUE,
    OvsCommand,
    resolve,
)

OP_MODEL = (BandwidthMaxOp, BandwidthMinOp)

_PROTECTED_QUEUE = 1


def _cap(op: BandwidthMaxOp, src_host: str) -> tuple[OvsCommand, ...]:
    rate = int(op.bw_mbps * 1000)
    burst = max(rate // 10, 1)
    return (
        OvsCommand(
            target="all",
            command=(
                f"ovs-vsctl set interface {{swport:{src_host}}} "
                f"ingress_policing_rate={rate} ingress_policing_burst={burst}"
            ),
        ),
    )


def _floor(op: BandwidthMinOp, src_host: str, src_mac: str,
           dst_mac: str) -> tuple[OvsCommand, ...]:
    """Build the htb queue and steer the flow into it. Unmeasured; see above."""
    bits = int(op.bw_mbps * 1_000_000)
    qos = OvsCommand(
        target="all",
        command=(
            f"ovs-vsctl -- set port {{swport:{src_host}}} qos=@newqos "
            f"-- --id=@newqos create qos type=linux-htb "
            f"queues={_PROTECTED_QUEUE}=@q1 "
            f"-- --id=@q1 create queue other-config:min-rate={bits}"
        ),
    )
    # Matched on the ordered pair rather than on the source alone. A floor is
    # granted to one flow; a dl_src-only match swept every packet the host
    # sent into the queue, including flows another verb was acting on.
    flow = OvsCommand(
        target="all",
        command=(
            f"ovs-ofctl add-flow {{switch}} 'table={TABLE_QUEUE},"
            f"priority={PRIORITY_QUEUE},dl_src={src_mac},dl_dst={dst_mac},"
            f"actions=set_queue:{_PROTECTED_QUEUE},"
            f"resubmit(,{TABLE_FORWARD})'"
        ),
    )
    return (qos, flow)


def to_commands(
    op: Union[BandwidthMaxOp, BandwidthMinOp],
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    src = resolve(endpoints, op.src)
    dst = resolve(endpoints, op.dst)
    if op.verb == "bandwidth_max":
        return _cap(op, src.host)
    return _floor(op, src.host, src.mac, dst.mac)
