"""Phase C (Mac): aggregate CaseResults into realization tables.

Two metrics per strategy: the share of fully satisfied intents (strict AND over
every ground-truth check), and the mean realization rate, which shows how far
off the failures were. Both are also split by annotated complexity, which is
the axis the report needs.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from bench.orchestrator import CaseResult

_STRATA = ("simple", "medium", "complex")


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def realization_rate(results: Sequence[CaseResult]) -> dict[str, float]:
    """Share of fully satisfied intents per strategy, in [0, 1]."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in results:
        buckets[r.strategy].append(1.0 if r.satisfied else 0.0)
    return {s: _mean(v) for s, v in buckets.items()}


def mean_realization(results: Sequence[CaseResult]) -> dict[str, float]:
    """Mean fraction of checks validated per strategy, in [0, 1]."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in results:
        buckets[r.strategy].append(r.realization_rate)
    return {s: _mean(v) for s, v in buckets.items()}


def by_complexity(results: Sequence[CaseResult]) -> dict[tuple[str, str], float]:
    """Share of fully satisfied intents per (strategy, annotated complexity)."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in results:
        buckets[(r.strategy, r.expected_complexity)].append(
            1.0 if r.satisfied else 0.0
        )
    return {k: _mean(v) for k, v in buckets.items()}


def render_table(results: Sequence[CaseResult]) -> str:
    """Markdown: one row per strategy, one column per complexity stratum.

    A (strategy, stratum) pair with no cases renders as ``n/a``, never
    ``0 %`` — the truth is "not measured", and collapsing that to zero
    would misreport it as a measured failure.
    """
    overall = realization_rate(results)
    partial = mean_realization(results)
    split = by_complexity(results)
    if not overall:
        return "_Aucun résultat._"

    header = "| Stratégie | " + " | ".join(_STRATA) + " | Global | Taux moyen |"
    lines = [header, "|" + "---|" * (len(_STRATA) + 3)]
    for strategy in sorted(overall):
        cells = []
        for stratum in _STRATA:
            value = split.get((strategy, stratum))
            cells.append("n/a" if value is None else f"{value * 100:.0f} %")
        lines.append(
            f"| {strategy} | " + " | ".join(cells)
            + f" | {overall[strategy] * 100:.0f} %"
            + f" | {partial[strategy] * 100:.0f} % |"
        )
    return "\n".join(lines)
