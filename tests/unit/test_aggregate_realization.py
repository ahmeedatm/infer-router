from __future__ import annotations

from bench.orchestrator import CaseResult
from experiments.aggregate_realization import realization_rate, render_table


def _r(intent, strat, ok):
    return CaseResult(intent_id=intent, strategy=strat, satisfied=ok, detail="")


def test_rate_per_strategy():
    results = [
        _r("i1", "light", True), _r("i2", "light", False),
        _r("i1", "heavy", True), _r("i2", "heavy", True),
    ]
    rates = realization_rate(results)
    assert rates["light"] == 0.5
    assert rates["heavy"] == 1.0


def test_render_table_contains_rows():
    table = render_table({"light": 0.5, "heavy": 1.0})
    assert "light" in table and "50" in table
    assert "heavy" in table and "100" in table
