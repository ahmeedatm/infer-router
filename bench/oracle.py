"""Positive control: the plan that satisfies an intent's own ground truth.

The negative control (``noop``) proves a check *can* fail. It cannot prove a
check can pass, and a check that always fails is as dead as one that always
passes — it just looks strict instead of lenient. ``path_used`` was exactly
that: unfailable-looking, in fact unpassable.

So each check is also mapped, mechanically, to the operation that realises it,
and the resulting plan is replayed like any other strategy. Every check then
carries a two-sided proof: it fails under ``noop`` and passes under ``oracle``.
A check that misses either side is still broken, and which side it misses says
what is wrong with it.

The derivation reads ``entry.checks`` only. Nothing here is hand-written per
intent, so the oracle cannot drift into an answer key that happens to pass:
if a check's realisation is wrong, every intent carrying that check fails
together and the defect is in this module, not in one row.

No model call, no API cost. Pure: no Mininet, no network.
"""
from __future__ import annotations

from typing import Iterator

from app.llm.intent_plan import (
    AllowOp,
    BandwidthMaxOp,
    BandwidthMinOp,
    BlockOp,
    IntentPlan,
    MirrorOp,
    Operation,
    PriorityOp,
    RerouteOp,
    Selector,
)
from bench.subset import (
    MirrorSeen,
    PathUsed,
    PingFail,
    PingOk,
    PortBlocked,
    PortOpen,
    SubsetEntry,
    ThroughputMax,
    ThroughputMin,
    TosMarked,
)
from bench.verbs.priority import TOS_BY_CLASS

#: Never resolves to a model, like ``noop``.
ORACLE_STRATEGY = "oracle"

_CLASS_BY_TOS = {tos: klass for klass, tos in TOS_BY_CLASS.items()}


class OracleError(RuntimeError):
    """Raised when a check has no mechanical realisation.

    Guessing here would produce a control that quietly stops covering a check
    while still reporting a plausible number, which is the failure mode this
    whole exercise exists to remove.
    """


def _probe_key(entry: SubsetEntry, host: str) -> str:
    """The endpoint name for a Mininet host, which ``mirror`` needs as a key.

    ``mirror_seen.probe_host`` is a host name; ``MirrorOp.to`` is an endpoint
    key. The subset is what connects the two.
    """
    for key, ref in entry.endpoints.items():
        if ref.host == host:
            return key
    raise OracleError(
        f"{entry.intent_id}: mirror probe host {host!r} has no endpoint; "
        f"known endpoints: {sorted(entry.endpoints)}"
    )


def _operations_for(check, entry: SubsetEntry) -> tuple[Operation, ...]:
    """The operation(s) that make one ground-truth check hold."""
    if isinstance(check, PingOk):
        # Base connectivity is total, so nothing is required. Handled by the
        # caller, which needs the plan to stay non-empty.
        return ()

    if isinstance(check, PingFail):
        return (BlockOp(verb="block", src=check.src, dst=check.dst),)

    if isinstance(check, PortBlocked):
        return (BlockOp(verb="block", src=check.src, dst=check.dst,
                        selector=Selector(proto=check.proto, port=check.port)),)

    if isinstance(check, PortOpen):
        # A permission is only observable as an exception, so the denial it
        # is an exception to is part of realising it.
        return (
            BlockOp(verb="block", src=check.src, dst=check.dst),
            AllowOp(verb="allow", src=check.src, dst=check.dst,
                    selector=Selector(proto=check.proto, port=check.port)),
        )

    if isinstance(check, ThroughputMax):
        return (BandwidthMaxOp(verb="bandwidth_max", src=check.src,
                               dst=check.dst, bw_mbps=check.max_mbps),)

    if isinstance(check, ThroughputMin):
        return (BandwidthMinOp(verb="bandwidth_min", src=check.src,
                               dst=check.dst, bw_mbps=check.min_mbps),)

    if isinstance(check, PathUsed):
        return (RerouteOp(verb="reroute", src=check.src, dst=check.dst,
                          via=check.via),)

    if isinstance(check, MirrorSeen):
        return (MirrorOp(verb="mirror", src=check.src, dst=check.dst,
                         to=_probe_key(entry, check.probe_host)),)

    if isinstance(check, TosMarked):
        klass = _CLASS_BY_TOS.get(check.tos)
        if klass is None:
            raise OracleError(
                f"{entry.intent_id}: no priority class carries ToS "
                f"{check.tos}; the vocabulary offers {sorted(_CLASS_BY_TOS)}"
            )
        return (PriorityOp(verb="priority", src=check.src, dst=check.dst,
                           klass=klass),)

    raise OracleError(f"{entry.intent_id}: no realisation for check {check!r}")


def _deduplicated(ops: Iterator[Operation]) -> tuple[Operation, ...]:
    """Keep first occurrences: two checks may imply the same operation."""
    seen: set = set()
    unique = []
    for op in ops:
        if op in seen:
            continue
        seen.add(op)
        unique.append(op)
    return tuple(unique)


def oracle_plan(entry: SubsetEntry) -> IntentPlan:
    """Build the plan that satisfies every check this intent is scored on."""
    operations = _deduplicated(
        op for check in entry.checks for op in _operations_for(check, entry)
    )
    if not operations:
        # Only reachable for an intent asking solely for connectivity that
        # already holds. An inert allow is the honest answer, and IntentPlan
        # requires at least one operation.
        keys = list(entry.endpoints)
        operations = (AllowOp(verb="allow", src=keys[0],
                              dst=keys[1] if len(keys) > 1 else keys[0]),)
    return IntentPlan(intent_id=entry.intent_id, operations=operations)
