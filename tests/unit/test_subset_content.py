from __future__ import annotations

from collections import Counter

from bench.subset import load_subset


def test_subset_holds_twenty_four_intents():
    assert len(load_subset()) == 24


def test_strata_are_balanced():
    counts = Counter(e.expected_complexity for e in load_subset())
    assert counts == {"simple": 8, "medium": 8, "complex": 8}


def test_simple_intents_carry_exactly_one_check():
    for entry in load_subset():
        if entry.expected_complexity == "simple":
            assert len(entry.checks) == 1, entry.intent_id


def test_complex_intents_carry_at_least_three_checks():
    for entry in load_subset():
        if entry.expected_complexity == "complex":
            assert len(entry.checks) >= 3, entry.intent_id


def test_every_check_type_appears_somewhere():
    seen = {c.check for e in load_subset() for c in e.checks}
    assert seen == {
        "ping_ok", "ping_fail", "throughput_max", "throughput_min",
        "port_blocked", "mirror_seen", "path_used", "tos_marked",
    }


def test_every_intent_targets_diamond4():
    assert all(e.topology == "diamond4" for e in load_subset())


def test_intent_ids_are_unique():
    ids = [e.intent_id for e in load_subset()]
    assert len(ids) == len(set(ids))
