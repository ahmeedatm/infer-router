"""Tests des fonctions pures de l'expérience H-C (séparabilité de la complexité).

H-C interroge la viabilité de l'estimateur de complexité : la complexité d'un
intent (simple/medium/complex) est-elle séparable à partir de son énoncé, une
fois encodé en embedding ? On valide ici la métrique de séparabilité hors
modèle, sur des embeddings synthétiques (aucun chargement de torch).

Stratégie : un k-NN en leave-one-out donne une borne basse honnête de la
séparabilité (chaque point est prédit sans se voir lui-même). On la compare au
baseline majoritaire, la référence "hasard intelligent" à battre.
"""
from __future__ import annotations

import numpy as np

from experiments.exp_c_complexity_separability import (
    loo_knn_accuracy,
    separability_report,
)


def _three_clusters() -> tuple[np.ndarray, list[str]]:
    """Trois grappes nettement disjointes, labels alignés sur les grappes."""
    rng = np.random.default_rng(0)
    centers = np.array([[0.0, 0.0], [50.0, 50.0], [-50.0, 50.0]])
    labels = ["simple", "medium", "complex"]
    points = []
    out_labels = []
    for center, label in zip(centers, labels):
        cloud = center + rng.normal(scale=0.5, size=(6, 2))
        points.extend(cloud.tolist())
        out_labels.extend([label] * 6)
    return np.array(points), out_labels


def test_separable_clusters_high_accuracy():
    embeddings, labels = _three_clusters()
    acc = loo_knn_accuracy(embeddings, labels, k=3)
    assert acc == 1.0


def test_random_embeddings_near_chance():
    # Embeddings sans structure : l'accuracy doit rester proche du hasard.
    rng = np.random.default_rng(42)
    embeddings = rng.normal(size=(30, 8))
    labels = (["simple"] * 10) + (["medium"] * 10) + (["complex"] * 10)
    acc = loo_knn_accuracy(embeddings, labels, k=3)
    # 3 classes équilibrées : hasard ≈ 0.33. On tolère une marge généreuse.
    assert acc <= 0.55


def test_accepts_list_of_lists():
    embeddings = [[0.0, 0.0], [0.1, 0.1], [9.0, 9.0], [9.1, 9.1]]
    labels = ["a", "a", "b", "b"]
    acc = loo_knn_accuracy(embeddings, labels, k=1)
    assert acc == 1.0


def test_k_reduced_when_larger_than_n_minus_one():
    # n=4 → au plus 3 voisins disponibles en LOO. k=10 ne doit pas planter.
    embeddings = [[0.0, 0.0], [0.1, 0.0], [9.0, 9.0], [9.0, 9.1]]
    labels = ["a", "a", "b", "b"]
    acc = loo_knn_accuracy(embeddings, labels, k=10)
    assert 0.0 <= acc <= 1.0


def test_report_majority_baseline():
    # 8 simple sur 20 → classe dominante à 0.4.
    labels = (["simple"] * 8) + (["medium"] * 7) + (["complex"] * 5)
    embeddings = np.random.default_rng(1).normal(size=(20, 4))
    report = separability_report(embeddings, labels)
    assert report["n"] == 20
    assert report["baseline_majoritaire"] == 0.4


def test_report_structure_and_per_class():
    embeddings, labels = _three_clusters()
    report = separability_report(embeddings, labels)
    assert set(report) == {
        "accuracy_loo",
        "n",
        "baseline_majoritaire",
        "par_classe",
    }
    assert report["accuracy_loo"] == 1.0
    assert report["n"] == 18
    # 3 classes à 6 exemplaires : baseline = 6/18.
    assert abs(report["baseline_majoritaire"] - 6 / 18) < 1e-9
    assert set(report["par_classe"]) == {"simple", "medium", "complex"}
    for stats in report["par_classe"].values():
        assert stats["accuracy"] == 1.0
        assert stats["n"] == 6
