import math
import pytest
from app.gpp import compute_priority, rank_models, ModelPriority


class TestComputePriority:
    def test_basic_formula(self):
        # p = alpha + omega * c / mu = 0.0 + 1.0 * 1.0 / 2.0 = 0.5
        assert compute_priority(alpha_i=0.0, mu_i=2.0, c=1.0, omega=1.0) == pytest.approx(0.5)

    def test_gold_standard_alpha_zero(self):
        # Gold standard: alpha=0, p = omega*c/mu
        assert compute_priority(alpha_i=0.0, mu_i=1.0, c=1.0, omega=1.0) == pytest.approx(1.0)

    def test_zero_mu_returns_inf(self):
        assert compute_priority(alpha_i=0.5, mu_i=0.0, c=1.0, omega=1.0) == math.inf

    def test_negative_mu_returns_inf(self):
        assert compute_priority(alpha_i=0.0, mu_i=-1.0, c=1.0, omega=1.0) == math.inf

    def test_higher_inaccuracy_raises_priority_value(self):
        p_accurate = compute_priority(alpha_i=0.0, mu_i=1.0, c=1.0, omega=1.0)
        p_inaccurate = compute_priority(alpha_i=0.5, mu_i=1.0, c=1.0, omega=1.0)
        assert p_inaccurate > p_accurate

    def test_faster_model_lowers_priority_value(self):
        p_slow = compute_priority(alpha_i=0.1, mu_i=1.0, c=1.0, omega=1.0)
        p_fast = compute_priority(alpha_i=0.1, mu_i=5.0, c=1.0, omega=1.0)
        assert p_fast < p_slow


class TestRankModels:
    def test_returns_all_models(self):
        models = [("Fast", "http://fast"), ("Accurate", "http://accurate")]
        ranked = rank_models(models, {"Fast": 0.1, "Accurate": 0.0}, {"Fast": 5.0, "Accurate": 1.0}, c=1.0, omega=1.0)
        assert len(ranked) == 2

    def test_sorted_ascending_priority(self):
        # Fast: p = 0.1 + 1.0/5.0 = 0.3
        # Accurate: p = 0.0 + 1.0/1.0 = 1.0
        # Fast has lower p → ranked first
        models = [("Fast", "http://fast"), ("Accurate", "http://accurate")]
        ranked = rank_models(models, {"Fast": 0.1, "Accurate": 0.0}, {"Fast": 5.0, "Accurate": 1.0}, c=1.0, omega=1.0)
        assert ranked[0].name == "Fast"
        assert ranked[1].name == "Accurate"

    def test_accurate_first_when_fast_very_inaccurate(self):
        # Fast: p = 0.9 + 1.0/5.0 = 1.1
        # Accurate: p = 0.0 + 1.0/1.0 = 1.0
        # Accurate has lower p → ranked first
        models = [("Fast", "http://fast"), ("Accurate", "http://accurate")]
        ranked = rank_models(models, {"Fast": 0.9, "Accurate": 0.0}, {"Fast": 5.0, "Accurate": 1.0}, c=1.0, omega=1.0)
        assert ranked[0].name == "Accurate"

    def test_model_priority_dataclass_fields(self):
        models = [("M1", "http://m1")]
        ranked = rank_models(models, {"M1": 0.2}, {"M1": 2.0}, c=1.0, omega=1.0)
        m = ranked[0]
        assert isinstance(m, ModelPriority)
        assert m.name == "M1"
        assert m.url == "http://m1"
        assert m.alpha == pytest.approx(0.2)
        assert m.mu == pytest.approx(2.0)
