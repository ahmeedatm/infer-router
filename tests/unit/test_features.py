"""Tests for the semantic-complexity feature extractor (``app.llm.features``).

These tests exercise the pure regex/heuristic feature extraction on small,
hand-controlled synthetic intents. No embedding model is loaded here: every
assertion is on integer/float proxies of the chapter-3 criteria
(n(e), p(e), |δ(e)|). Per project rules the extractor is pure and immutable.
"""
from __future__ import annotations

from app.llm.features import (
    FEATURE_NAMES,
    extract_features,
    features_matrix,
)

SIMPLE_INTENT = "What is the current RSRP on cell gNB-207-C1?"
COMPLEX_INTENT = (
    "gNB cluster {gNB-101, gNB-102} serves a URLLC slice (latency <= 1 ms, "
    "PDB <= 0.5 ms) and two eMBB slices at 78 percent PRB utilisation. "
    "Arbitrate PRB allocation across all three slices such that the URLLC "
    "latency SLA is never breached while eMBB throughput degradation stays "
    "below 15 percent, without exceeding 12 handovers per minute, ensuring "
    "the AMF and SMF signalling load on the N2 interface remains stable."
)


def test_extract_features_returns_all_named_keys() -> None:
    feats = extract_features(SIMPLE_INTENT)
    assert set(feats.keys()) == set(FEATURE_NAMES)
    assert list(feats.keys()) == list(FEATURE_NAMES)  # stable ordering


def test_extract_features_values_are_floats() -> None:
    feats = extract_features(COMPLEX_INTENT)
    assert all(isinstance(v, float) for v in feats.values())


def test_simple_intent_has_low_entity_and_zero_constraints() -> None:
    feats = extract_features(SIMPLE_INTENT)
    # One gNB identifier, no constraint markers, one sentence.
    assert feats["n_entities"] == 1.0
    assert feats["n_constraints"] == 0.0
    assert feats["n_sentences"] == 1.0
    assert feats["n_domains"] == 1.0  # RAN only (RSRP, gNB, cell)


def test_complex_intent_has_high_entities_and_constraints() -> None:
    feats = extract_features(COMPLEX_INTENT)
    # Multiple gNB ids + NF acronyms + interface → many entities.
    assert feats["n_entities"] >= 4.0
    # "such that", "while", "without", "ensuring" → several constraints.
    assert feats["n_constraints"] >= 3.0
    # RAN (gNB/PRB) + core (AMF/SMF/N2) + slice (URLLC/eMBB) → ≥ 2 domains.
    assert feats["n_domains"] >= 2.0


def test_complex_intent_dominates_simple_on_proxies() -> None:
    simple = extract_features(SIMPLE_INTENT)
    complex_ = extract_features(COMPLEX_INTENT)
    for key in ("n_entities", "n_constraints", "n_domains", "n_numbers", "n_tokens"):
        assert complex_[key] > simple[key], key


def test_n_numbers_counts_unit_values() -> None:
    text = "Keep latency below 1 ms and throughput above 10 Mbps at 90 percent load."
    feats = extract_features(text)
    # "1 ms", "10 Mbps", "90 percent" → 3 numeric-with-unit values.
    assert feats["n_numbers"] >= 3.0


def test_n_sentences_counts_terminators() -> None:
    text = "First check the cell. Then verify the slice. Finally report status."
    feats = extract_features(text)
    assert feats["n_sentences"] == 3.0


def test_empty_text_yields_zeros() -> None:
    feats = extract_features("")
    assert all(v == 0.0 for v in feats.values())


def test_extract_features_rejects_non_string() -> None:
    import pytest

    with pytest.raises(TypeError):
        extract_features(123)  # type: ignore[arg-type]


def test_features_matrix_rows_align_with_names() -> None:
    texts = [SIMPLE_INTENT, COMPLEX_INTENT]
    matrix, names = features_matrix(texts)
    assert names == list(FEATURE_NAMES)
    assert len(matrix) == 2
    assert all(len(row) == len(names) for row in matrix)
    # Row values match extract_features in the same column order.
    expected_first = [extract_features(SIMPLE_INTENT)[n] for n in names]
    assert matrix[0] == expected_first


def test_features_matrix_empty_input() -> None:
    matrix, names = features_matrix([])
    assert matrix == []
    assert names == list(FEATURE_NAMES)


def test_features_matrix_cols_subset_returns_only_requested() -> None:
    cols = ["n_entities", "n_constraints", "n_domains", "n_numbers"]
    matrix, names = features_matrix([SIMPLE_INTENT, COMPLEX_INTENT], cols=cols)
    assert names == cols
    assert all(len(row) == len(cols) for row in matrix)
    expected_first = [extract_features(SIMPLE_INTENT)[n] for n in cols]
    assert matrix[0] == expected_first


def test_features_matrix_cols_preserves_requested_order() -> None:
    cols = ["n_domains", "n_entities"]  # deliberately not FEATURE_NAMES order
    matrix, names = features_matrix([COMPLEX_INTENT], cols=cols)
    assert names == cols
    feats = extract_features(COMPLEX_INTENT)
    assert matrix[0] == [feats["n_domains"], feats["n_entities"]]


def test_features_matrix_cols_none_returns_all() -> None:
    matrix_all, names_all = features_matrix([SIMPLE_INTENT])
    matrix_default, names_default = features_matrix([SIMPLE_INTENT], cols=None)
    assert names_all == names_default == list(FEATURE_NAMES)
    assert matrix_all == matrix_default


def test_features_matrix_cols_rejects_unknown_name() -> None:
    import pytest

    with pytest.raises(KeyError):
        features_matrix([SIMPLE_INTENT], cols=["n_entities", "n_bogus"])


def test_extract_features_does_not_mutate_input() -> None:
    text = SIMPLE_INTENT
    extract_features(text)
    assert text == SIMPLE_INTENT  # str is immutable; guard against accidental reassign
