"""Tests de la fonction pure compute_agreement (expérience A)."""
from __future__ import annotations

from experiments.exp_a_agreement import compute_agreement


def _rec(intent_id, level, q_light, q_heavy, label_A, label_B):
    return {
        "intent_id": intent_id,
        "expected_complexity": level,
        "q_light": q_light,
        "q_heavy": q_heavy,
        "label_A": label_A,
        "label_B": label_B,
        "error": None,
    }


def test_full_agreement():
    # juge préfère heavy (q plus haut) ; heavy est en A ; référence dit A -> accord
    responses = [_rec("i1", "complex", 0.4, 0.9, "heavy", "light")]
    verdicts = {"i1": "A"}
    out = compute_agreement(responses, verdicts)
    assert out["agreement"] == 1.0
    assert out["agree_count"] == 1


def test_disagreement():
    # juge préfère heavy (=A) mais la référence dit B -> désaccord
    responses = [_rec("i1", "complex", 0.4, 0.9, "heavy", "light")]
    verdicts = {"i1": "B"}
    out = compute_agreement(responses, verdicts)
    assert out["agreement"] == 0.0


def test_egal_symmetric_is_agreement():
    responses = [_rec("i1", "simple", 0.7, 0.7, "light", "heavy")]
    verdicts = {"i1": "egal"}
    out = compute_agreement(responses, verdicts)
    assert out["agreement"] == 1.0


def test_egal_asymmetric_is_disagreement():
    # juge égal mais référence tranche A -> désaccord (choix conservateur)
    responses = [_rec("i1", "simple", 0.7, 0.7, "light", "heavy")]
    verdicts = {"i1": "A"}
    out = compute_agreement(responses, verdicts)
    assert out["agreement"] == 0.0


def test_partial_and_by_complexity():
    responses = [
        _rec("i1", "simple", 0.5, 0.5, "light", "heavy"),   # juge egal
        _rec("i2", "complex", 0.3, 0.9, "heavy", "light"),  # juge A
    ]
    verdicts = {"i1": "egal", "i2": "B"}  # i1 accord, i2 désaccord
    out = compute_agreement(responses, verdicts)
    assert out["n"] == 2
    assert out["agreement"] == 0.5
    assert out["by_complexity"]["simple"]["rate"] == 1.0
    assert out["by_complexity"]["complex"]["rate"] == 0.0


def test_hb_preference_counts():
    responses = [
        _rec("i1", "complex", 0.3, 0.9, "heavy", "light"),
        _rec("i2", "complex", 0.2, 0.8, "light", "heavy"),
    ]
    # référence préfère heavy dans les deux cas
    verdicts = {"i1": "A", "i2": "B"}
    out = compute_agreement(responses, verdicts)
    pref = out["reference_preference_by_complexity"]["complex"]
    assert pref["heavy"] == 2
    assert pref["light"] == 0


def test_missing_verdict_skipped():
    responses = [_rec("i1", "simple", 0.4, 0.9, "heavy", "light")]
    out = compute_agreement(responses, {})  # pas de verdict
    assert out["n"] == 0
    assert out["agreement"] == 0.0


def test_error_record_skipped():
    rec = _rec("i1", "simple", 0.4, 0.9, "heavy", "light")
    rec["error"] = "OpenRouterError: boom"
    out = compute_agreement([rec], {"i1": "A"})
    assert out["n"] == 0
