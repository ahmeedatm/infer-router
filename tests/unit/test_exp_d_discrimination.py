"""Tests de la fonction pure discrimination_score (expérience D).

L'expérience D mesure si le juge détecte une dégradation ciblée : pour chaque
paire (réponse correcte, réponse dégradée), la vérité-terrain est connue (la
correcte est toujours meilleure). On vérifie la comptabilisation des
préférences correctes, des égalités et des inversions, globalement et par
type d'erreur injectée.
"""
from __future__ import annotations

from experiments.exp_d_discrimination import discrimination_score


def _res(intent_id, error_type, q_correct, q_degraded):
    return {
        "intent_id": intent_id,
        "error_type": error_type,
        "q_correct": q_correct,
        "q_degraded": q_degraded,
    }


def test_full_correct_preference():
    # Le juge préfère systématiquement la réponse correcte.
    results = [
        _res("i1", "wrong_number", 1.0, 0.5),
        _res("i2", "missing_step", 0.8, 0.4),
        _res("i3", "false_claim", 0.9, 0.2),
    ]
    out = discrimination_score(results)
    assert out["n"] == 3
    assert out["correct_preference_rate"] == 1.0
    assert out["tie_rate"] == 0.0
    assert out["inversion_rate"] == 0.0
    assert out["correct_count"] == 3


def test_all_ties():
    # Le juge ne voit aucune différence.
    results = [
        _res("i1", "wrong_number", 0.7, 0.7),
        _res("i2", "missing_step", 0.5, 0.5),
    ]
    out = discrimination_score(results)
    assert out["tie_rate"] == 1.0
    assert out["correct_preference_rate"] == 0.0
    assert out["inversion_rate"] == 0.0
    assert out["tie_count"] == 2


def test_all_inversions():
    # Le juge se trompe : il préfère la dégradée.
    results = [
        _res("i1", "wrong_number", 0.3, 0.9),
        _res("i2", "false_claim", 0.2, 0.6),
    ]
    out = discrimination_score(results)
    assert out["inversion_rate"] == 1.0
    assert out["correct_preference_rate"] == 0.0
    assert out["tie_rate"] == 0.0
    assert out["inversion_count"] == 2


def test_mixed_global_rates():
    results = [
        _res("i1", "wrong_number", 1.0, 0.5),  # correct
        _res("i2", "missing_step", 0.5, 0.5),  # tie
        _res("i3", "false_claim", 0.2, 0.9),   # inversion
        _res("i4", "wrong_number", 0.8, 0.1),  # correct
    ]
    out = discrimination_score(results)
    assert out["n"] == 4
    assert out["correct_preference_rate"] == 0.5
    assert out["tie_rate"] == 0.25
    assert out["inversion_rate"] == 0.25


def test_breakdown_by_error_type():
    results = [
        _res("i1", "wrong_number", 1.0, 0.5),  # correct
        _res("i2", "wrong_number", 0.4, 0.4),  # tie
        _res("i3", "missing_step", 0.2, 0.9),  # inversion
        _res("i4", "false_claim", 0.9, 0.3),   # correct
    ]
    out = discrimination_score(results)
    by = out["by_error_type"]

    assert by["wrong_number"]["n"] == 2
    assert by["wrong_number"]["correct_count"] == 1
    assert by["wrong_number"]["tie_count"] == 1
    assert by["wrong_number"]["inversion_count"] == 0
    assert by["wrong_number"]["correct_preference_rate"] == 0.5

    assert by["missing_step"]["n"] == 1
    assert by["missing_step"]["inversion_count"] == 1
    assert by["missing_step"]["inversion_rate"] == 1.0

    assert by["false_claim"]["n"] == 1
    assert by["false_claim"]["correct_count"] == 1
    assert by["false_claim"]["correct_preference_rate"] == 1.0


def test_empty_results():
    out = discrimination_score([])
    assert out["n"] == 0
    assert out["correct_preference_rate"] == 0.0
    assert out["tie_rate"] == 0.0
    assert out["inversion_rate"] == 0.0
    assert out["by_error_type"] == {}
