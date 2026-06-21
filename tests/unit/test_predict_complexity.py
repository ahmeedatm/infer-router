"""Tests for the persisted complexity estimator's predict path.

These tests train a tiny RandomForest on the length-independent subset, persist
it to a temporary joblib bundle, and check that :func:`predict_complexity`
rebuilds the matrix from exactly the persisted ``feature_names`` (the substance
proxies, no length). They never touch the real artifact under ``data/``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from experiments.train_complexity_estimator import (
    PERSISTED_FEATURES,
    predict_complexity,
)

SIMPLE = "What is the current RSRP on cell gNB-207-C1?"
COMPLEX = (
    "gNB cluster {gNB-101, gNB-102} serves a URLLC slice (latency <= 1 ms) and "
    "two eMBB slices such that the URLLC SLA is never breached while throughput "
    "stays below 15 percent degradation, ensuring AMF and SMF load on N2 stays "
    "stable, without exceeding 12 handovers per minute."
)


def test_persisted_features_excludes_length() -> None:
    assert PERSISTED_FEATURES == (
        "n_entities",
        "n_constraints",
        "n_domains",
        "n_numbers",
    )
    assert "n_tokens" not in PERSISTED_FEATURES
    assert "n_sentences" not in PERSISTED_FEATURES


def _write_bundle(path: Path) -> None:
    """Train a minimal RF on the substance subset and persist a bundle."""
    import joblib
    from sklearn.ensemble import RandomForestClassifier

    from app.llm.features import features_matrix

    texts = [SIMPLE, SIMPLE, COMPLEX, COMPLEX]
    y = np.array(["simple", "simple", "complex", "complex"])
    rows, names = features_matrix(texts, cols=PERSISTED_FEATURES)
    clf = RandomForestClassifier(n_estimators=20, random_state=42)
    clf.fit(np.asarray(rows, dtype=float), y)
    joblib.dump(
        {
            "model": clf,
            "model_type": "RandomForestClassifier",
            "feature_names": list(names),
            "classes": ["simple", "medium", "complex"],
        },
        path,
    )


def test_predict_complexity_uses_persisted_subset(tmp_path: Path) -> None:
    model_path = tmp_path / "estimator.joblib"
    _write_bundle(model_path)

    preds = predict_complexity([SIMPLE, COMPLEX], model_path=model_path)

    assert preds == ["simple", "complex"]


def test_predict_complexity_no_mismatch_on_subset_bundle(tmp_path: Path) -> None:
    """A subset bundle (4 features) must not raise the old mismatch error."""
    model_path = tmp_path / "estimator.joblib"
    _write_bundle(model_path)

    # Would previously fail because features_matrix returned all 6 names.
    preds = predict_complexity([COMPLEX], model_path=model_path)
    assert preds and all(isinstance(p, str) for p in preds)


def test_predict_complexity_missing_model_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        predict_complexity([SIMPLE], model_path=tmp_path / "absent.joblib")
