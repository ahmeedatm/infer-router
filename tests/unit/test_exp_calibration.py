"""Tests de la fonction pure aggregate_quality (calibration, objectif 1).

La calibration mesure la qualité réelle (q du juge) par tier (light/heavy) et
par complexité (simple/medium/complex), à partir d'enregistrements où chaque
intent a été servi par les DEUX tiers avec la MÊME checklist. La fonction est
pure (pas d'I/O) : on la teste sur des données synthétiques.

Contrat de aggregate_quality(records) -> dict :
    record = {intent_id, complexity, q_light, q_heavy}
    sortie :
      - "matrix"[complexity][tier]  = q moyen (tier ∈ {light, heavy})
      - "gap"[complexity]           = q_heavy_moyen - q_light_moyen
      - "n"[complexity]             = nb d'intents de cette complexité
      - "overall"["light"|"heavy"|"gap"] = moyennes globales
"""
from __future__ import annotations

from experiments.exp_calibration import aggregate_quality


def _rec(intent_id, complexity, q_light, q_heavy):
    return {
        "intent_id": intent_id,
        "complexity": complexity,
        "q_light": q_light,
        "q_heavy": q_heavy,
    }


def test_matrix_means_per_tier_and_complexity():
    records = [
        _rec("s1", "simple", 0.9, 1.0),
        _rec("s2", "simple", 0.7, 0.8),
        _rec("c1", "complex", 0.2, 0.9),
    ]
    out = aggregate_quality(records)
    assert out["matrix"]["simple"]["light"] == 0.8  # (0.9+0.7)/2
    assert out["matrix"]["simple"]["heavy"] == 0.9   # (1.0+0.8)/2
    assert out["matrix"]["complex"]["light"] == 0.2
    assert out["matrix"]["complex"]["heavy"] == 0.9
    assert out["n"]["simple"] == 2
    assert out["n"]["complex"] == 1


def test_heavy_minus_light_gap_per_complexity():
    records = [
        _rec("s1", "simple", 0.9, 0.95),   # gap 0.05
        _rec("m1", "medium", 0.6, 0.85),   # gap 0.25
        _rec("c1", "complex", 0.3, 0.9),   # gap 0.60
    ]
    out = aggregate_quality(records)
    assert abs(out["gap"]["simple"] - 0.05) < 1e-9
    assert abs(out["gap"]["medium"] - 0.25) < 1e-9
    assert abs(out["gap"]["complex"] - 0.60) < 1e-9


def test_small_gap_on_simple_supports_h_b():
    # H-B : sur le simple, le light suffit (écart heavy-light négligeable).
    records = [
        _rec("s1", "simple", 0.95, 0.96),
        _rec("s2", "simple", 0.90, 0.92),
    ]
    out = aggregate_quality(records)
    assert out["gap"]["simple"] < 0.05


def test_overall_means_and_gap():
    records = [
        _rec("s1", "simple", 0.8, 1.0),
        _rec("c1", "complex", 0.2, 0.6),
    ]
    out = aggregate_quality(records)
    assert abs(out["overall"]["light"] - 0.5) < 1e-9   # (0.8+0.2)/2
    assert abs(out["overall"]["heavy"] - 0.8) < 1e-9   # (1.0+0.6)/2
    assert abs(out["overall"]["gap"] - 0.3) < 1e-9


def test_records_missing_a_complexity_bucket_are_absent():
    # Aucune entrée "medium" : la clé ne doit pas apparaître (pas de division par 0).
    records = [_rec("s1", "simple", 0.7, 0.8)]
    out = aggregate_quality(records)
    assert "simple" in out["matrix"]
    assert "medium" not in out["matrix"]
    assert "medium" not in out["gap"]


def test_empty_records():
    out = aggregate_quality([])
    assert out["matrix"] == {}
    assert out["gap"] == {}
    assert out["n"] == {}
    assert out["overall"] == {"light": 0.0, "heavy": 0.0, "gap": 0.0}
