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


def test_complex_intents_carry_at_least_two_checks():
    """The bound was three. Retiring ``throughput_min`` from the measured
    scope took the third check off c-002, c-003 and c-008; their text still
    asks for three operations, but only two of them are observable on this
    bench. Two is the floor that keeps a complex intent scored on more than
    one dimension. Padding the count back to three with a check that cannot
    fail would be worse than lowering it."""
    for entry in load_subset():
        if entry.expected_complexity == "complex":
            assert len(entry.checks) >= 2, entry.intent_id


def test_every_intent_keeps_at_least_one_check():
    """``throughput_min`` was struck from five intents. One left with no check
    would be scored on an empty conjunction, i.e. satisfied for free.
    pydantic's ``min_length`` already refuses that; asserting it here is what
    keeps the reason attached to the rule."""
    for entry in load_subset():
        assert entry.checks, entry.intent_id


def test_every_check_type_appears_somewhere():
    """What the bench measures, enumerated. This is what stops a stratum
    rotting silently: a check type that quietly stops being used anywhere
    fails here rather than disappearing from the results unnoticed."""
    seen = {c.check for e in load_subset() for c in e.checks}
    assert seen == {
        "ping_ok", "ping_fail", "throughput_max",
        "port_blocked", "port_open", "mirror_seen", "path_used", "tos_marked",
    }


def test_throughput_min_is_not_measured_anywhere():
    """Deliberately out of scope, and pinned so it stays a decision rather
    than an accident. The positive control failed it on all six intents that
    carried it: the ``bandwidth_min`` verb puts its htb queue on the port
    facing the source, never on the s2-s4 bottleneck the contention runs
    through, so the guarantee could not reach the measurement. The verb stays
    in the vocabulary (a model may legitimately emit it, and the parser must
    accept it); no check observes it. Re-adding one without moving the queue
    re-adds an unpassable check."""
    assert not [
        e.intent_id for e in load_subset()
        for c in e.checks if c.check == "throughput_min"
    ]


def test_no_intent_is_scored_on_ping_ok_alone():
    """Base connectivity is total by default and a selector-less ``allow``
    translates to zero commands, so an intent whose only check is ``ping_ok``
    cannot be failed by any plan. Combined with a denial it is a useful
    non-regression check; alone it measures nothing. The negative control
    caught this on s-allow-001, which scored 1/1 with an inert plan."""
    for entry in load_subset():
        kinds = {c.check for c in entry.checks}
        assert kinds != {"ping_ok"}, entry.intent_id


def test_every_intent_targets_diamond4():
    assert all(e.topology == "diamond4" for e in load_subset())


def test_intent_ids_are_unique():
    ids = [e.intent_id for e in load_subset()]
    assert len(ids) == len(set(ids))


def test_the_noop_control_is_inert_on_every_real_subset_entry():
    """The negative control is only a control if it applies cleanly and
    changes nothing, for all 24 intents. An entry where it failed to
    translate would score 0 for the wrong reason and stop proving anything
    about the checks."""
    from bench.translator import translate_plan
    from experiments.run_realworld_validation import noop_plan

    for entry in load_subset():
        plan = noop_plan(entry)
        assert translate_plan(plan, entry.endpoints) == (), entry.intent_id
