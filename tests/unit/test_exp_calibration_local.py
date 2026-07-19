"""Tests des fonctions pures de la calibration locale (fusion + ordre).

Contrats :
- merge_stored_records : union par intent_id, première source prioritaire,
  ne conserve que complexity/checklist/q_heavy.
- interleave_by_complexity : ordre round-robin simple/medium/complex,
  déterministe, chaque préfixe du run couvre les classes de façon équilibrée.
"""
from experiments.exp_calibration_local import (
    interleave_by_complexity,
    merge_stored_records,
)


def _rec(iid, cx, q_heavy=0.5, extra=None):
    rec = {
        "intent_id": iid,
        "complexity": cx,
        "checklist": [f"crit-{iid}"],
        "q_heavy": q_heavy,
        "cost_heavy": 0.01,
        "model_light": "llama",
    }
    if extra:
        rec.update(extra)
    return rec


class TestMergeStoredRecords:
    def test_union_without_duplicates(self):
        first = [_rec("a", "simple"), _rec("b", "medium")]
        second = [_rec("b", "medium"), _rec("c", "complex")]
        merged = merge_stored_records([first, second])
        assert set(merged) == {"a", "b", "c"}

    def test_first_source_wins_on_conflict(self):
        first = [_rec("a", "simple", q_heavy=0.9)]
        second = [_rec("a", "simple", q_heavy=0.1)]
        merged = merge_stored_records([first, second])
        assert merged["a"]["q_heavy"] == 0.9

    def test_keeps_only_reusable_fields(self):
        merged = merge_stored_records([[_rec("a", "simple")]])
        assert set(merged["a"]) == {"complexity", "checklist", "q_heavy"}

    def test_empty_sources_yield_empty_dict(self):
        assert merge_stored_records([]) == {}
        assert merge_stored_records([[]]) == {}


class TestInterleaveByComplexity:
    def test_round_robin_alternates_classes(self):
        records = {
            "s1": {"complexity": "simple"},
            "s2": {"complexity": "simple"},
            "m1": {"complexity": "medium"},
            "m2": {"complexity": "medium"},
            "c1": {"complexity": "complex"},
            "c2": {"complexity": "complex"},
        }
        order = interleave_by_complexity(records)
        # Premier tour : une occurrence de chaque classe.
        first_round = {records[iid]["complexity"] for iid in order[:3]}
        assert first_round == {"simple", "medium", "complex"}

    def test_every_prefix_is_near_balanced(self):
        records = {f"s{i}": {"complexity": "simple"} for i in range(4)}
        records |= {f"m{i}": {"complexity": "medium"} for i in range(4)}
        records |= {f"c{i}": {"complexity": "complex"} for i in range(4)}
        order = interleave_by_complexity(records)
        for prefix_len in (3, 6, 9, 12):
            prefix = order[:prefix_len]
            counts = {}
            for iid in prefix:
                cx = records[iid]["complexity"]
                counts[cx] = counts.get(cx, 0) + 1
            assert max(counts.values()) - min(counts.values()) <= 1

    def test_exhausted_class_does_not_block_others(self):
        records = {
            "s1": {"complexity": "simple"},
            "m1": {"complexity": "medium"},
            "m2": {"complexity": "medium"},
            "c1": {"complexity": "complex"},
            "c2": {"complexity": "complex"},
            "c3": {"complexity": "complex"},
        }
        order = interleave_by_complexity(records)
        assert len(order) == 6
        assert set(order) == set(records)

    def test_deterministic(self):
        records = {
            "b": {"complexity": "simple"},
            "a": {"complexity": "simple"},
            "c": {"complexity": "medium"},
        }
        assert interleave_by_complexity(records) == interleave_by_complexity(records)
