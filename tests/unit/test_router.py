"""Unit tests for app.llm.router (pure routing decision, ch.3 formalization).

These tests are fully synthetic: no network, no Ollama, no API key. They
pin the chapter 3 equations: admissibility M(e), objective R*(e) = argmax q,
the degenerate case (no admissible candidate -> None), and the Pareto
tie-break (cost asc, then latency asc).
"""
import pytest
from pydantic import ValidationError

from app.llm.router import RouteCandidate, admissible, select


def _c(model_id: str, q: float, cost: float, latency_ms: float) -> RouteCandidate:
    return RouteCandidate(model_id=model_id, q=q, cost=cost, latency_ms=latency_ms)


class TestRouteCandidate:
    def test_valid_candidate(self):
        cand = _c("m1", 0.8, 0.001, 300.0)
        assert cand.model_id == "m1"
        assert cand.q == 0.8

    def test_bounds_allowed(self):
        assert _c("m", 0.0, 0.0, 0.0).q == 0.0
        assert _c("m", 1.0, 0.0, 0.0).q == 1.0

    def test_q_above_one_rejected(self):
        with pytest.raises(ValidationError):
            _c("m", 1.1, 0.0, 0.0)

    def test_q_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            _c("m", -0.1, 0.0, 0.0)

    def test_negative_cost_rejected(self):
        with pytest.raises(ValidationError):
            _c("m", 0.5, -0.01, 0.0)

    def test_negative_latency_rejected(self):
        with pytest.raises(ValidationError):
            _c("m", 0.5, 0.0, -1.0)

    def test_is_frozen(self):
        cand = _c("m", 0.5, 0.0, 0.0)
        with pytest.raises(ValidationError):
            cand.q = 0.9


class TestAdmissible:
    def test_keeps_candidates_within_both_budgets(self):
        cands = (
            _c("a", 0.7, 0.001, 200.0),
            _c("b", 0.9, 0.002, 400.0),
        )
        result = admissible(cands, l_max=500.0, c_max=0.01)
        assert {c.model_id for c in result} == {"a", "b"}

    def test_excludes_over_latency(self):
        cands = (_c("a", 0.7, 0.001, 600.0),)
        assert admissible(cands, l_max=500.0, c_max=0.01) == ()

    def test_excludes_over_cost(self):
        cands = (_c("a", 0.7, 0.05, 200.0),)
        assert admissible(cands, l_max=500.0, c_max=0.01) == ()

    def test_boundary_is_inclusive(self):
        cands = (_c("a", 0.7, 0.01, 500.0),)
        result = admissible(cands, l_max=500.0, c_max=0.01)
        assert len(result) == 1

    def test_returns_tuple(self):
        result = admissible((_c("a", 0.7, 0.0, 0.0),), l_max=1.0, c_max=1.0)
        assert isinstance(result, tuple)


class TestSelect:
    def test_nominal_picks_best_admissible_q(self):
        cands = (
            _c("low", 0.5, 0.001, 100.0),
            _c("best", 0.9, 0.001, 100.0),
            _c("mid", 0.7, 0.001, 100.0),
        )
        assert select(cands, l_max=500.0, c_max=0.01) == "best"

    def test_top_q_over_latency_budget_is_skipped(self):
        cands = (
            _c("fast-good", 0.8, 0.001, 100.0),
            _c("slow-best", 0.95, 0.001, 900.0),
        )
        assert select(cands, l_max=500.0, c_max=0.01) == "fast-good"

    def test_all_over_budget_returns_none(self):
        cands = (
            _c("slow", 0.95, 0.001, 900.0),
            _c("expensive", 0.9, 0.5, 100.0),
        )
        assert select(cands, l_max=500.0, c_max=0.01) is None

    def test_empty_candidates_returns_none(self):
        assert select((), l_max=500.0, c_max=0.01) is None

    def test_tie_on_q_breaks_by_cost_then_latency(self):
        cands = (
            _c("expensive", 0.9, 0.005, 100.0),
            _c("cheap-slow", 0.9, 0.001, 400.0),
            _c("cheap-fast", 0.9, 0.001, 200.0),
        )
        assert select(cands, l_max=500.0, c_max=0.01) == "cheap-fast"

    def test_tie_on_q_and_cost_breaks_by_latency(self):
        cands = (
            _c("slow", 0.9, 0.001, 400.0),
            _c("fast", 0.9, 0.001, 200.0),
        )
        assert select(cands, l_max=500.0, c_max=0.01) == "fast"
