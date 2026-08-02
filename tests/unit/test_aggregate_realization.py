from __future__ import annotations

from bench.orchestrator import CaseResult
from experiments.aggregate_realization import (
    by_complexity, mean_realization, realization_rate, render_table,
)


def _r(strategy, complexity, satisfied, rate) -> CaseResult:
    return CaseResult(
        intent_id="i", strategy=strategy, expected_complexity=complexity,
        satisfied=satisfied, realization_rate=rate, detail="",
    )


_RESULTS = [
    _r("heavy", "simple", True, 1.0),
    _r("heavy", "complex", True, 1.0),
    _r("light", "simple", True, 1.0),
    _r("light", "complex", False, 0.5),
]


def test_realization_rate_is_the_share_of_satisfied_cases():
    assert realization_rate(_RESULTS) == {"heavy": 1.0, "light": 0.5}


def test_mean_realization_averages_the_partial_scores():
    assert mean_realization(_RESULTS) == {"heavy": 1.0, "light": 0.75}


def test_by_complexity_splits_each_strategy():
    got = by_complexity(_RESULTS)
    assert got[("light", "simple")] == 1.0
    assert got[("light", "complex")] == 0.0
    assert got[("heavy", "complex")] == 1.0


def test_render_table_reports_both_metrics_and_every_stratum():
    table = render_table(_RESULTS)
    assert "Stratégie" in table
    assert "simple" in table and "complex" in table
    assert "100 %" in table and "50 %" in table


def test_empty_results_render_without_crashing():
    assert render_table([]) != ""


def _row_cells(table: str, strategy: str) -> list[str]:
    """Strip a rendered row down to its bare cell values, in column order."""
    for line in table.splitlines():
        if line.startswith(f"| {strategy} |"):
            return [cell.strip() for cell in line.strip("|").split("|")]
    raise AssertionError(f"no row for strategy {strategy!r} in:\n{table}")


def test_render_table_distinguishes_unmeasured_from_genuinely_zero():
    # heavy/simple has one satisfied case (-> 100 %), heavy/medium has no
    # case at all (-> n/a, not 0 %), heavy/complex has one failed case
    # (-> a genuine 0 %). The three must read differently: an untested
    # stratum is not the same finding as a stratum that failed outright.
    mixed = [
        _r("heavy", "simple", True, 1.0),
        _r("heavy", "complex", False, 0.0),
    ]
    cells = _row_cells(render_table(mixed), "heavy")
    # columns: strategy, simple, medium, complex, Global, Taux moyen
    assert cells == ["heavy", "100 %", "n/a", "0 %", "50 %", "50 %"]
