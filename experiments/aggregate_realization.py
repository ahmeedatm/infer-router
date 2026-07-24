"""Phase C (Mac): aggregate CaseResults into an intent-realization table."""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from bench.orchestrator import CaseResult


def realization_rate(results: Sequence[CaseResult]) -> dict[str, float]:
    """Mean of `satisfied` per strategy, in [0, 1]."""
    hits: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for r in results:
        total[r.strategy] += 1
        hits[r.strategy] += 1 if r.satisfied else 0
    return {s: hits[s] / total[s] for s in total}


def render_table(rates: dict[str, float]) -> str:
    """Markdown table sorted by strategy name."""
    lines = ["| Stratégie | Taux de réalisation |", "|---|---|"]
    for strategy in sorted(rates):
        lines.append(f"| {strategy} | {rates[strategy] * 100:.0f} % |")
    return "\n".join(lines)
