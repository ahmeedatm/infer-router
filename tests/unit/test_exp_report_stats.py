"""Unit tests for experiments.exp_report_stats (analyses dérivées du benchmark).

Fully synthetic: no network, no result file, no matplotlib. These pin the
functions the report's added figures and intervals rest on:

- paired bootstrap of a mean, with its reproducible seed;
- the Pareto frontier swept from the quality floor, including the operating
  point a coarse sweep hides;
- interpolation of the frontier at an arbitrary budget, which is how the
  router is compared to a fixed strategy at equal cost;
- the specialisation break-even, where a specialist pool stops losing;
- the effect of a hard latency budget, including the unroutable case.
"""
import pytest

from experiments.exp_report_stats import (
    bootstrap_mean,
    expected_specialisation_delta,
    paired_differences,
    pareto_frontier,
    quality_at_cost,
    specialisation_break_even,
    tighten_latency,
)


class TestBootstrapMean:
    def test_estimate_is_the_sample_mean(self):
        result = bootstrap_mean([0.0, 1.0, 2.0, 3.0])
        assert result.estimate == pytest.approx(1.5)

    def test_interval_brackets_the_estimate(self):
        result = bootstrap_mean([0.1, 0.4, 0.9, 0.3, 0.7, 0.5])
        assert result.low <= result.estimate <= result.high

    def test_constant_sample_yields_a_degenerate_interval(self):
        result = bootstrap_mean([0.5] * 10)
        assert result.low == pytest.approx(0.5)
        assert result.high == pytest.approx(0.5)

    def test_same_seed_gives_the_same_interval(self):
        values = [0.2, 0.8, 0.1, 0.9, 0.5]
        first = bootstrap_mean(values, draws=500, seed=7)
        second = bootstrap_mean(values, draws=500, seed=7)
        assert (first.low, first.high) == (second.low, second.high)

    def test_wider_level_gives_a_wider_interval(self):
        values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        narrow = bootstrap_mean(values, draws=2000, seed=3, level=50.0)
        wide = bootstrap_mean(values, draws=2000, seed=3, level=99.0)
        assert wide.high - wide.low > narrow.high - narrow.low

    def test_empty_sample_is_rejected(self):
        with pytest.raises(ValueError, match="vide"):
            bootstrap_mean([])

    @pytest.mark.parametrize("level", [0.0, 100.0, -5.0, 140.0])
    def test_out_of_range_level_is_rejected(self, level):
        with pytest.raises(ValueError, match="level"):
            bootstrap_mean([0.1, 0.2], level=level)


class TestPairedDifferences:
    def _indexed(self):
        return {
            "a": {"i1": {"q": 0.8}, "i2": {"q": 0.6}},
            "b": {"i1": {"q": 0.5}, "i2": {"q": 0.6}},
        }

    def test_difference_is_computed_per_intent(self):
        diffs = paired_differences(self._indexed(), "a", "b")
        assert diffs.tolist() == pytest.approx([0.3, 0.0])

    def test_only_shared_intents_are_paired(self):
        indexed = self._indexed()
        indexed["a"]["i3"] = {"q": 1.0}
        assert paired_differences(indexed, "a", "b").size == 2

    def test_disjoint_strategies_are_rejected(self):
        indexed = {"a": {"i1": {"q": 0.5}}, "b": {"i9": {"q": 0.5}}}
        with pytest.raises(ValueError, match="commun"):
            paired_differences(indexed, "a", "b")


class TestParetoFrontier:
    # Expected light quality per complexity comes from config; the fixture
    # below only needs the three labels to exist.
    COMPLEXITIES = ["simple", "medium", "complex", "simple"]
    LIGHT = [0.6, 0.3, 0.2, 0.7]
    HEAVY = [0.9, 0.9, 0.9, 0.9]

    def test_extremes_are_all_light_and_all_heavy(self):
        frontier = pareto_frontier(self.COMPLEXITIES, self.LIGHT, self.HEAVY)
        assert frontier[0].n_light == len(self.COMPLEXITIES)
        assert frontier[-1].n_light == 0

    def test_points_are_ordered_by_increasing_cost(self):
        frontier = pareto_frontier(self.COMPLEXITIES, self.LIGHT, self.HEAVY)
        costs = [p.cost for p in frontier]
        assert costs == sorted(costs)

    def test_quality_increases_with_cost(self):
        frontier = pareto_frontier(self.COMPLEXITIES, self.LIGHT, self.HEAVY)
        qualities = [p.quality for p in frontier]
        assert qualities == sorted(qualities)

    def test_three_complexity_levels_give_four_operating_points(self):
        # The report claimed three: with three levels and two tiers, a floor
        # can free 0, 1, 2 or 3 levels to the light tier, hence four.
        frontier = pareto_frontier(self.COMPLEXITIES, self.LIGHT, self.HEAVY)
        assert len(frontier) == 4

    def test_a_coarse_sweep_hides_an_operating_point(self):
        fine = pareto_frontier(self.COMPLEXITIES, self.LIGHT, self.HEAVY, step=0.01)
        coarse = pareto_frontier(self.COMPLEXITIES, self.LIGHT, self.HEAVY, step=0.10)
        assert len(coarse) < len(fine)


class TestQualityAtCost:
    FRONTIER = pareto_frontier(
        ["simple", "medium", "complex"], [0.6, 0.3, 0.2], [0.9, 0.9, 0.9]
    )

    def test_interpolates_between_two_operating_points(self):
        low, high = self.FRONTIER[0], self.FRONTIER[1]
        midpoint = (low.cost + high.cost) / 2
        expected = (low.quality + high.quality) / 2
        assert quality_at_cost(self.FRONTIER, midpoint) == pytest.approx(expected)

    def test_returns_the_exact_value_on_an_operating_point(self):
        point = self.FRONTIER[1]
        assert quality_at_cost(self.FRONTIER, point.cost) == pytest.approx(
            point.quality
        )

    def test_clamps_outside_the_frontier(self):
        assert quality_at_cost(self.FRONTIER, -1.0) == pytest.approx(
            self.FRONTIER[0].quality
        )
        assert quality_at_cost(self.FRONTIER, 1e9) == pytest.approx(
            self.FRONTIER[-1].quality
        )


class TestSpecialisation:
    def test_break_even_balances_gain_and_loss(self):
        # 0.137 / (0.038 + 0.137) = 0.783
        assert specialisation_break_even(0.038, 0.137) == pytest.approx(0.783, abs=1e-3)

    def test_expected_delta_is_null_at_the_break_even(self):
        gain, loss = 0.038, 0.137
        accuracy = specialisation_break_even(gain, loss)
        assert expected_specialisation_delta(accuracy, gain, loss) == pytest.approx(
            0.0, abs=1e-9
        )

    def test_perfect_routing_yields_the_full_gain(self):
        assert expected_specialisation_delta(1.0, 0.038, 0.137) == pytest.approx(0.038)

    def test_always_wrong_routing_yields_the_full_loss(self):
        assert expected_specialisation_delta(0.0, 0.038, 0.137) == pytest.approx(-0.137)

    def test_symmetric_gain_and_loss_break_even_at_half(self):
        assert specialisation_break_even(0.1, 0.1) == pytest.approx(0.5)

    def test_negative_magnitudes_are_rejected(self):
        with pytest.raises(ValueError, match="magnitudes"):
            specialisation_break_even(0.038, -0.137)

    def test_null_effects_have_no_break_even(self):
        with pytest.raises(ValueError, match="point mort"):
            specialisation_break_even(0.0, 0.0)

    @pytest.mark.parametrize("accuracy", [-0.1, 1.5])
    def test_out_of_range_accuracy_is_rejected(self, accuracy):
        with pytest.raises(ValueError, match="accuracy"):
            expected_specialisation_delta(accuracy, 0.038, 0.137)


class TestTightenLatency:
    def _indexed(self):
        # i1: both tiers fit. i2: only the light tier fits. i3: neither fits.
        return {
            "always_light": {
                "i1": {"q": 0.4, "cost": 0.001, "latency_ms": 5_000.0},
                "i2": {"q": 0.3, "cost": 0.001, "latency_ms": 8_000.0},
                "i3": {"q": 0.2, "cost": 0.001, "latency_ms": 90_000.0},
            },
            "always_heavy": {
                "i1": {"q": 0.9, "cost": 0.02, "latency_ms": 9_000.0},
                "i2": {"q": 0.95, "cost": 0.02, "latency_ms": 50_000.0},
                "i3": {"q": 0.9, "cost": 0.02, "latency_ms": 80_000.0},
            },
            "inferrouter": {
                "i1": {"q": 0.9, "cost": 0.02, "latency_ms": 9_000.0},
                "i2": {"q": 0.95, "cost": 0.02, "latency_ms": 50_000.0},
                "i3": {"q": 0.9, "cost": 0.02, "latency_ms": 80_000.0},
            },
        }

    def test_a_loose_budget_changes_nothing(self):
        outcome = tighten_latency(self._indexed(), 1e9)
        assert outcome.n_unroutable == 0
        assert outcome.n_forced_light == 0
        assert outcome.quality == pytest.approx((0.9 + 0.95 + 0.9) / 3)

    def test_an_intent_breaching_on_every_tier_is_unroutable(self):
        outcome = tighten_latency(self._indexed(), 10_000.0)
        assert outcome.n_unroutable == 1

    def test_the_router_falls_back_when_only_the_heavy_breaches(self):
        outcome = tighten_latency(self._indexed(), 10_000.0)
        assert outcome.n_forced_light == 1
        # i1 keeps the heavy (0.9), i2 falls back to the light (0.3).
        assert outcome.quality == pytest.approx((0.9 + 0.3) / 2)

    def test_a_budget_excluding_everything_reports_no_quality(self):
        outcome = tighten_latency(self._indexed(), 1.0)
        assert outcome.n_unroutable == 3
        assert outcome.quality is None
        assert outcome.cost is None

    def test_tightening_never_raises_the_cost(self):
        loose = tighten_latency(self._indexed(), 1e9)
        tight = tighten_latency(self._indexed(), 10_000.0)
        assert tight.cost <= loose.cost

    @pytest.mark.parametrize("budget", [0.0, -5.0])
    def test_non_positive_budget_is_rejected(self, budget):
        with pytest.raises(ValueError, match="l_max_ms"):
            tighten_latency(self._indexed(), budget)
