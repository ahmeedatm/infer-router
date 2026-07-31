"""Verbs ``bandwidth_max`` and ``bandwidth_min``.

``bandwidth_max`` caps a flow with OVS ingress policing on the switch port
facing the source. ``bandwidth_min`` guarantees a floor instead: it builds a
linux-htb queue carrying ``min-rate`` on the outbound port and steers the
protected flow into it. A floor is only observable under contention, which the
bench creates with a competing flow over the capacity-limited core link.
"""
from __future__ import annotations

from typing import Union

from app.llm.intent_plan import BandwidthMaxOp, BandwidthMinOp
from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, resolve

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


def _floor(op: BandwidthMinOp, src_host: str, src_mac: str) -> tuple[OvsCommand, ...]:
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
    flow = OvsCommand(
        target="all",
        command=(
            f"ovs-ofctl add-flow {{switch}} 'priority=150,dl_src={src_mac},"
            f"actions=set_queue:{_PROTECTED_QUEUE},normal'"
        ),
    )
    return (qos, flow)


def to_commands(
    op: Union[BandwidthMaxOp, BandwidthMinOp],
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    src = resolve(endpoints, op.src)
    resolve(endpoints, op.dst)
    if op.verb == "bandwidth_max":
        return _cap(op, src.host)
    return _floor(op, src.host, src.mac)
