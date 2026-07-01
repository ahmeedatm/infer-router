"""Evaluation formulas for InferRouter-LLM (chapter 3).

Pure, dependency-free implementations of the report's evaluation formulas,
kept out of any experiment script so the application owns them and they are
unit-tested in isolation. No network, no Ollama, no numpy.

Formulas:

- Latency decomposition T(e) = T_est + T_rout + T_inf + T_juge. The judge runs
  off the critical path, so :attr:`LatencyBreakdown.critical_path` (the latency
  the operator perceives) excludes T_juge, while :attr:`LatencyBreakdown.total`
  is the full decomposition.
- Average Inference Quality AIQ = (1/|T|) * sum_e q_{R*(e)}(e): the mean quality
  of the selected models over an evaluation set. See :func:`aiq`.
- Latency percentiles P50 / P99 by linear interpolation (numpy-compatible). See
  :func:`percentile`, :func:`p50`, :func:`p99`.
"""
from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field


class LatencyBreakdown(BaseModel):
    """Immutable decomposition of the end-to-end latency T(e) of one intent.

    Attributes:
        t_est: Complexity-estimation time (ms).
        t_rout: Routing-decision time (ms).
        t_inf: Target-model inference time (ms), the dominant term.
        t_juge: Judge evaluation time (ms), run off the critical path.
    """

    model_config = ConfigDict(frozen=True)

    t_est: float = Field(ge=0.0)
    t_rout: float = Field(ge=0.0)
    t_inf: float = Field(ge=0.0)
    t_juge: float = Field(ge=0.0)

    @property
    def total(self) -> float:
        """Full decomposition T(e) = T_est + T_rout + T_inf + T_juge (ms)."""
        return self.t_est + self.t_rout + self.t_inf + self.t_juge

    @property
    def critical_path(self) -> float:
        """Perceived latency T_est + T_rout + T_inf (judge excluded)."""
        return self.t_est + self.t_rout + self.t_inf


def aiq(qualities: Sequence[float]) -> float:
    """Average Inference Quality: mean of the selected models' qualities.

    Args:
        qualities: Quality scores q_{R*(e)}(e) in [0, 1], one per evaluated
            intent.

    Returns:
        The mean quality, or 0.0 for an empty set.

    Raises:
        ValueError: if any quality falls outside [0, 1] (boundary validation).
    """
    out_of_range = [q for q in qualities if q < 0.0 or q > 1.0]
    if out_of_range:
        raise ValueError(
            f"qualities must lie in [0, 1]; got out-of-range {out_of_range}."
        )
    n = len(qualities)
    if n == 0:
        return 0.0
    return sum(qualities) / n


def percentile(values: Sequence[float], pct: float) -> float:
    """Percentile by linear interpolation, matching numpy's default method.

    Input order does not matter; the values are sorted internally.

    Args:
        values: Sample values (e.g. per-intent latencies in ms).
        pct: Percentile rank in [0, 100].

    Returns:
        The interpolated percentile, or 0.0 for an empty sample.

    Raises:
        ValueError: if ``pct`` is outside [0, 100] (boundary validation).
    """
    if pct < 0.0 or pct > 100.0:
        raise ValueError(f"pct must lie in [0, 100]; got {pct}.")
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + frac * (ordered[high] - ordered[low])


def p50(values: Sequence[float]) -> float:
    """Median latency P50 (ms)."""
    return percentile(values, 50.0)


def p99(values: Sequence[float]) -> float:
    """Tail latency P99 (ms)."""
    return percentile(values, 99.0)
