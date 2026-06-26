"""Séparabilité de la complexité des intents par embeddings.

Hypothèse testée : la complexité d'un intent réseau (``simple`` / ``medium`` /
``complex``) est récupérable depuis le seul énoncé textuel, une fois encodé en
embedding sentence-transformers. C'est la condition de viabilité de
l'estimateur de complexité du routeur (sentence-transformers + classifier).

Le cœur est une métrique pure et testable : un k-NN évalué en leave-one-out.
Chaque point est classé à partir des autres uniquement, ce qui donne une borne
basse honnête sur un petit jeu (20 intents). On compare cette accuracy au
baseline majoritaire (fréquence de la classe dominante), la référence "hasard
intelligent" à battre.

Le ``main`` charge le modèle réel et fait du calcul lourd (torch). Les imports
correspondants sont différés dans ``main`` pour que les tests de la fonction
pure n'aient pas à charger torch. Le premier run télécharge le modèle (~80 Mo).

Lancer :  .venv/bin/python -m experiments.exp_c_complexity_separability
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.neighbors import KNeighborsClassifier

RESULTS_DIR = Path("experiments/results")
PCA_PATH = RESULTS_DIR / "exp_c_pca.png"
COMPLEXITY_ORDER: tuple[str, ...] = ("simple", "medium", "complex")
DEFAULT_K = 3


def _as_matrix(embeddings) -> np.ndarray:
    """Normalise l'entrée en matrice float 2D (n×d), validation aux frontières."""
    matrix = np.asarray(embeddings, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(
            f"embeddings doit être 2D (n×d), reçu ndim={matrix.ndim}."
        )
    if matrix.shape[0] == 0:
        raise ValueError("embeddings est vide.")
    return matrix


def _effective_k(k: int, n: int) -> int:
    """Réduit k au plus grand voisinage exploitable en leave-one-out."""
    if k < 1:
        raise ValueError(f"k doit être >= 1, reçu {k}.")
    return max(1, min(k, n - 1))


def loo_knn_accuracy(embeddings, labels, k: int = DEFAULT_K) -> float:
    """Accuracy d'un k-NN en leave-one-out.

    Pour chaque point, on prédit son label depuis les ``n-1`` autres et on
    retourne la proportion de prédictions correctes. Fonction pure (aucune I/O,
    aucun modèle d'embeddings chargé).

    Args:
        embeddings: matrice n×d (np.ndarray ou liste de listes).
        labels: liste de ``n`` labels (str).
        k: nombre de voisins. Réduit automatiquement si ``k > n-1``.

    Returns:
        Accuracy dans [0.0, 1.0].

    Raises:
        ValueError: embeddings non 2D / vide, ou taille incohérente avec labels.
    """
    matrix = _as_matrix(embeddings)
    labels = list(labels)
    n = matrix.shape[0]
    if len(labels) != n:
        raise ValueError(
            f"labels ({len(labels)}) doit avoir la même longueur que "
            f"embeddings ({n})."
        )
    if n < 2:
        raise ValueError("Au moins 2 points sont nécessaires pour le LOO.")

    eff_k = _effective_k(k, n)
    correct = 0
    indices = np.arange(n)
    for i in range(n):
        train_idx = indices[indices != i]
        clf = KNeighborsClassifier(n_neighbors=eff_k)
        clf.fit(matrix[train_idx], [labels[j] for j in train_idx])
        predicted = clf.predict(matrix[i : i + 1])[0]
        if predicted == labels[i]:
            correct += 1
    return correct / n


def _majority_baseline(labels: list[str]) -> float:
    """Fréquence de la classe la plus représentée."""
    counts = Counter(labels)
    return max(counts.values()) / len(labels)


def _per_class_accuracy(
    embeddings, labels: list[str], k: int
) -> dict[str, dict]:
    """Accuracy LOO restreinte aux points de chaque classe (rappel par classe)."""
    matrix = _as_matrix(embeddings)
    n = matrix.shape[0]
    eff_k = _effective_k(k, n)
    indices = np.arange(n)
    buckets: dict[str, dict[str, int]] = {
        label: {"correct": 0, "n": 0} for label in set(labels)
    }
    for i in range(n):
        train_idx = indices[indices != i]
        clf = KNeighborsClassifier(n_neighbors=eff_k)
        clf.fit(matrix[train_idx], [labels[j] for j in train_idx])
        predicted = clf.predict(matrix[i : i + 1])[0]
        bucket = buckets[labels[i]]
        bucket["n"] += 1
        if predicted == labels[i]:
            bucket["correct"] += 1
    return {
        label: {
            "n": b["n"],
            "correct": b["correct"],
            "accuracy": b["correct"] / b["n"] if b["n"] else 0.0,
        }
        for label, b in buckets.items()
    }


def separability_report(embeddings, labels, k: int = DEFAULT_K) -> dict:
    """Rapport de séparabilité complet. Fonction pure.

    Args:
        embeddings: matrice n×d (np.ndarray ou liste de listes).
        labels: liste de ``n`` labels (str).
        k: nombre de voisins du k-NN.

    Returns:
        dict avec ``accuracy_loo``, ``n``, ``baseline_majoritaire``
        (fréquence de la classe dominante, référence à battre) et
        ``par_classe`` (n / correct / accuracy par label).
    """
    labels = list(labels)
    return {
        "accuracy_loo": loo_knn_accuracy(embeddings, labels, k),
        "n": len(labels),
        "baseline_majoritaire": _majority_baseline(labels),
        "par_classe": _per_class_accuracy(embeddings, labels, k),
    }


# ── Runner (modèle réel + tracé). Imports lourds différés. NON testé. ─────────


def _encode_texts(texts: list[str], model_name: str) -> np.ndarray:
    """Encode les énoncés en embeddings (charge sentence-transformers / torch)."""
    from sentence_transformers import SentenceTransformer  # lazy import

    model = SentenceTransformer(model_name)
    return np.asarray(model.encode(texts, show_progress_bar=False), dtype=float)


def _save_pca_plot(embeddings: np.ndarray, labels: list[str], path: Path) -> None:
    """Projette en 2D (PCA) et sauvegarde un nuage coloré par complexité."""
    import matplotlib  # lazy import

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA

    coords = PCA(n_components=2, random_state=0).fit_transform(embeddings)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7, 6))
    palette = {"simple": "#2ca02c", "medium": "#ff7f0e", "complex": "#d62728"}
    for label in COMPLEXITY_ORDER:
        mask = np.array([lab == label for lab in labels])
        if mask.any():
            ax.scatter(
                coords[mask, 0],
                coords[mask, 1],
                label=label,
                color=palette.get(label),
                s=80,
                edgecolors="black",
                linewidths=0.5,
            )
    ax.set_title("Exp. H-C — projection PCA des intents par complexité")
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.legend(title="complexité")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _print_report(report: dict, model_name: str) -> None:
    print("=== Expérience H-C — séparabilité de la complexité (embeddings) ===")
    print(f"Modèle d'embeddings : {model_name}")
    acc = report["accuracy_loo"]
    base = report["baseline_majoritaire"]
    print(
        f"n = {report['n']}  ·  accuracy LOO k-NN = {acc:.0%}  ·  "
        f"baseline majoritaire = {base:.0%}"
    )
    print(f"  gain sur baseline = {acc - base:+.0%}")
    print("\nAccuracy par classe :")
    for label in COMPLEXITY_ORDER:
        stats = report["par_classe"].get(label)
        if stats:
            print(
                f"  {label:8s}: {stats['accuracy']:.0%} "
                f"({stats['correct']}/{stats['n']})"
            )

    print("\n=== Verdict — viabilité de l'estimateur de complexité ===")
    if acc >= base + 0.20:
        print(f"  OK  accuracy {acc:.0%} bat nettement le baseline {base:.0%}.")
    elif acc > base:
        print(f"  ~   accuracy {acc:.0%} dépasse le baseline {base:.0%} de peu.")
    else:
        print(f"  X   accuracy {acc:.0%} <= baseline {base:.0%} : non séparable.")


def main() -> None:
    from app import config
    from app.llm.intents import load_intents

    intents = load_intents()
    texts = [it.text for it in intents]
    labels = [it.expected_complexity for it in intents]

    print(f"Encodage de {len(texts)} intents avec {config.EMBEDDING_MODEL} ...")
    embeddings = _encode_texts(texts, config.EMBEDDING_MODEL)

    report = separability_report(embeddings, labels)
    _save_pca_plot(embeddings, labels, PCA_PATH)
    print(f"Projection PCA sauvegardée : {PCA_PATH}\n")
    _print_report(report, config.EMBEDDING_MODEL)


if __name__ == "__main__":
    main()
