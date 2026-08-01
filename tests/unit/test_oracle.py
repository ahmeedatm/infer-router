"""The positive control must be derivable from ground truth alone.

The negative control proves a check *can* fail. It cannot prove a check can
pass: a check that always fails is as dead as one that always passes, and it
looks merely strict. These tests pin the mechanical derivation check -> the
operation that satisfies it, so the oracle stays a property of the subset and
never becomes a hand-tuned answer key.
"""
from __future__ import annotations

import pytest

from app.llm.intent_plan import IntentPlan
from bench.oracle import OracleError, oracle_plan
from bench.subset import (
    EndpointRef,
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
    load_subset,
)
from bench.translator import translate_plan


def _entry(*checks, endpoints=None) -> SubsetEntry:
    return SubsetEntry(
        intent_id="t-001", text="t", domain="core", criticality="med",
        expected_complexity="simple", topology="diamond4",
        endpoints=endpoints or {
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
            "c": EndpointRef(host="h2", mac="00:00:00:00:00:02"),
            "probe": EndpointRef(host="h4", mac="00:00:00:00:00:04"),
        },
        checks=checks,
    )


def _ops(*checks):
    return oracle_plan(_entry(*checks)).operations


def test_ping_fail_becomes_a_block_on_that_pair():
    (op,) = _ops(PingFail(check="ping_fail", src="a", dst="b"))
    assert (op.verb, op.src, op.dst, op.selector) == ("block", "a", "b", None)


def test_throughput_max_becomes_a_cap_at_that_ceiling():
    (op,) = _ops(ThroughputMax(check="throughput_max", src="a", dst="b",
                               max_mbps=8.0))
    assert (op.verb, op.bw_mbps) == ("bandwidth_max", 8.0)


def test_throughput_min_becomes_a_floor_at_that_guarantee():
    (op,) = _ops(ThroughputMin(check="throughput_min", src="a", dst="b",
                               min_mbps=5.0, contender_src="c",
                               contender_dst="b"))
    assert (op.verb, op.bw_mbps, op.src, op.dst) == ("bandwidth_min", 5.0, "a", "b")


def test_path_used_becomes_a_reroute_via_that_switch():
    (op,) = _ops(PathUsed(check="path_used", src="a", dst="b",
                          via="s3", not_via="s2"))
    assert (op.verb, op.via) == ("reroute", "s3")


def test_port_blocked_becomes_a_selected_block():
    (op,) = _ops(PortBlocked(check="port_blocked", src="a", dst="b",
                             port=22, proto="tcp"))
    assert op.verb == "block"
    assert (op.selector.proto, op.selector.port) == ("tcp", 22)


def test_port_open_becomes_a_broad_block_plus_a_narrow_allow():
    """The permission is only observable as an exception, so the oracle has
    to install the denial it is an exception to."""
    ops = _ops(PortOpen(check="port_open", src="a", dst="b",
                        port=9100, proto="tcp"))
    assert [op.verb for op in ops] == ["block", "allow"]
    assert ops[0].selector is None
    assert (ops[1].selector.proto, ops[1].selector.port) == ("tcp", 9100)


def test_mirror_seen_becomes_a_mirror_to_the_probe_endpoint():
    (op,) = _ops(MirrorSeen(check="mirror_seen", src="a", dst="b",
                            probe_host="h4", min_packets=3))
    assert (op.verb, op.to) == ("mirror", "probe")


def test_tos_marked_becomes_the_priority_class_carrying_that_byte():
    (high,) = _ops(TosMarked(check="tos_marked", src="a", dst="b", tos=184))
    (low,) = _ops(TosMarked(check="tos_marked", src="a", dst="b", tos=32))
    assert (high.verb, high.klass) == ("priority", "high")
    assert low.klass == "low"


def test_an_unmappable_tos_is_refused_rather_than_guessed():
    with pytest.raises(OracleError):
        _ops(TosMarked(check="tos_marked", src="a", dst="b", tos=7))


def test_a_probe_host_with_no_endpoint_is_refused():
    with pytest.raises(OracleError):
        oracle_plan(_entry(
            MirrorSeen(check="mirror_seen", src="a", dst="b",
                       probe_host="h9", min_packets=3),
            endpoints={"a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
                       "b": EndpointRef(host="h3", mac="00:00:00:00:00:03")},
        ))


def test_ping_ok_contributes_no_operation():
    """Base connectivity is total by default, so honouring "X reaches Y"
    requires nothing. The plan still has to be non-empty, and the inert
    allow is what an operator would legitimately answer here."""
    reachable = PingOk(check="ping_ok", src="a", dst="b")
    ops = _ops(reachable)
    assert [op.verb for op in ops] == ["allow"]
    assert translate_plan(IntentPlan(intent_id="t-001", operations=ops),
                          _entry(reachable).endpoints) == ()


def test_operations_are_not_repeated():
    """Two checks can imply the same operation; installing it twice would
    make the oracle's command list unrepresentative of a real plan."""
    ops = _ops(
        PingFail(check="ping_fail", src="a", dst="b"),
        PingFail(check="ping_fail", src="a", dst="b"),
    )
    assert len(ops) == 1


# --- the real subset --------------------------------------------------------

def test_every_subset_entry_yields_a_translatable_oracle_plan():
    """A positive control that fails to translate would score zero for a
    bench reason and prove nothing about the checks it was meant to exercise."""
    for entry in load_subset():
        plan = oracle_plan(entry)
        assert translate_plan(plan, entry.endpoints), entry.intent_id


def test_the_oracle_emits_at_least_one_operation_per_check_bearing_verb():
    """Guard against a check type silently falling through the derivation and
    leaving the oracle unable to satisfy it."""
    for entry in load_subset():
        plan = oracle_plan(entry)
        assert len(plan.operations) >= 1, entry.intent_id
