"""Unit tests for app.llm.router (pure routing decision, ch.3 formalization).

These tests are fully synthetic: no network, no Ollama, no API key. They pin
the (revised) chapter 3 objective: minimise cost subject to q >= q_min and
the hard SLA budgets. Covered: SLA admissibility M_sla(e), the cost-minimising
choice among quality-feasible candidates, the best-effort fallback when none
reaches q_min, the degenerate case (no SLA-admissible candidate -> None), and
the latency tie-break at equal cost.
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
    def test_picks_cheapest_meeting_floor(self):
        # light and heavy both clear q_min=0.60 -> cheapest (light) wins,
        # even though heavy has higher quality.
        cands = (
            _c("light", 0.64, 0.0002, 8000.0),
            _c("heavy", 0.94, 0.02, 41000.0),
        )
        assert select(cands, q_min=0.60, l_max=1e9, c_max=1e9) == "light"

    def test_floor_forces_costlier_model(self):
        # light is cheap but below floor -> the pricier heavy that clears it wins.
        cands = (
            _c("light", 0.39, 0.0002, 8000.0),
            _c("heavy", 0.86, 0.02, 41000.0),
        )
        assert select(cands, q_min=0.60, l_max=1e9, c_max=1e9) == "heavy"

    def test_low_floor_lets_cheapest_win_despite_gap(self):
        # with a low floor, even a weak-but-passing light is chosen for cost.
        cands = (
            _c("light", 0.32, 0.0002, 8000.0),
            _c("heavy", 0.84, 0.02, 41000.0),
        )
        assert select(cands, q_min=0.30, l_max=1e9, c_max=1e9) == "light"

    def test_best_effort_when_none_meets_floor(self):
        # floor unreachable by all -> fall back to the highest-quality model.
        cands = (
            _c("light", 0.32, 0.0002, 8000.0),
            _c("heavy", 0.84, 0.02, 41000.0),
        )
        assert select(cands, q_min=0.95, l_max=1e9, c_max=1e9) == "heavy"

    def test_sla_budget_is_hard_even_if_floor_met(self):
        # heavy clears the floor but violates the latency budget -> excluded;
        # light (also clears floor) is chosen.
        cands = (
            _c("light", 0.64, 0.0002, 8000.0),
            _c("heavy", 0.94, 0.02, 41000.0),
        )
        assert select(cands, q_min=0.60, l_max=10000.0, c_max=1e9) == "light"

    def test_all_over_sla_budget_returns_none(self):
        cands = (
            _c("slow", 0.95, 0.001, 900.0),
            _c("expensive", 0.9, 0.5, 100.0),
        )
        assert select(cands, q_min=0.5, l_max=500.0, c_max=0.01) is None

    def test_empty_candidates_returns_none(self):
        assert select((), q_min=0.5, l_max=500.0, c_max=0.01) is None

    def test_tie_on_cost_breaks_by_latency(self):
        # two models clear the floor at equal cost -> the faster wins.
        cands = (
            _c("slow", 0.9, 0.001, 400.0),
            _c("fast", 0.9, 0.001, 200.0),
        )
        assert select(cands, q_min=0.5, l_max=500.0, c_max=0.01) == "fast"
