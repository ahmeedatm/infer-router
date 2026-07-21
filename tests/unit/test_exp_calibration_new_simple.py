"""Tests de select_fresh_simple_intents (fonction pure, ligne simple propre).

Contrat : ne retient que la complexité "simple", exclut les intent_id déjà
couverts par un run stocké, tri déterministe, borné à n.
"""
from app.llm.schema import Intent
from experiments.exp_calibration_new_simple import select_fresh_simple_intents


def _intent(iid, cx="simple"):
    return Intent(
        id=iid, text=f"intent {iid}", domain="core",
        expected_complexity=cx, criticality="low", slice_type=None,
    )


class TestSelectFreshSimpleIntents:
    def test_filters_to_simple_only(self):
        intents = [_intent("s1", "simple"), _intent("m1", "medium"), _intent("c1", "complex")]
        selected = select_fresh_simple_intents(intents, set(), 10)
        assert [it.id for it in selected] == ["s1"]

    def test_excludes_covered_ids(self):
        intents = [_intent("s1"), _intent("s2"), _intent("s3")]
        selected = select_fresh_simple_intents(intents, {"s2"}, 10)
        assert [it.id for it in selected] == ["s1", "s3"]

    def test_deterministic_sort_by_id(self):
        intents = [_intent("s3"), _intent("s1"), _intent("s2")]
        selected = select_fresh_simple_intents(intents, set(), 10)
        assert [it.id for it in selected] == ["s1", "s2", "s3"]

    def test_bounded_to_n(self):
        intents = [_intent(f"s{i}") for i in range(10)]
        selected = select_fresh_simple_intents(intents, set(), 3)
        assert len(selected) == 3

    def test_empty_when_all_covered(self):
        intents = [_intent("s1"), _intent("s2")]
        selected = select_fresh_simple_intents(intents, {"s1", "s2"}, 10)
        assert selected == ()

    def test_no_simple_intents_yields_empty(self):
        intents = [_intent("m1", "medium"), _intent("c1", "complex")]
        selected = select_fresh_simple_intents(intents, set(), 10)
        assert selected == ()
