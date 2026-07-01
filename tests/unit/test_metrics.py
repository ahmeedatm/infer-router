"""Unit tests for app.llm.metrics (ch.3 evaluation formulas).

Fully synthetic: no network, no Ollama, no API key. These pin the chapter 3
equations that were previously buried in an experiment script:

- Latency decomposition T(e) = T_est + T_rout + T_inf + T_juge, plus the
  perceived critical path T_est + T_rout + T_inf (judge is off the path).
- Average Inference Quality AIQ = mean of the selected models' qualities.
- P50 / P99 latency percentiles (linear interpolation, numpy-compatible).
"""
import pytest
from pydantic import ValidationError

from app.llm.metrics import LatencyBreakdown, aiq, p50, p99, percentile


class TestLatencyBreakdown:
    def test_total_sums_the_four_components(self):
        b = LatencyBreakdown(t_est=10.0, t_rout=1.0, t_inf=300.0, t_juge=500.0)
        assert b.total == pytest.approx(811.0)

    def test_critical_path_excludes_the_judge(self):
        b = LatencyBreakdown(t_est=10.0, t_rout=1.0, t_inf=300.0, t_juge=500.0)
        assert b.critical_path == pytest.approx(311.0)

    def test_zero_components_allowed(self):
        b = LatencyBreakdown(t_est=0.0, t_rout=0.0, t_inf=0.0, t_juge=0.0)
        assert b.total == 0.0
        assert b.critical_path == 0.0

    def test_frozen(self):
        b = LatencyBreakdown(t_est=1.0, t_rout=1.0, t_inf=1.0, t_juge=1.0)
        with pytest.raises(ValidationError):
            b.t_inf = 2.0

    def test_negative_component_rejected(self):
        with pytest.raises(ValidationError):
            LatencyBreakdown(t_est=-1.0, t_rout=0.0, t_inf=0.0, t_juge=0.0)


class TestAIQ:
    def test_mean_of_qualities(self):
        assert aiq([1.0, 0.0, 0.5]) == pytest.approx(0.5)

    def test_single_value(self):
        assert aiq([0.73]) == pytest.approx(0.73)

    def test_empty_is_zero(self):
        assert aiq([]) == 0.0

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            aiq([0.5, 1.2])
        with pytest.raises(ValueError):
            aiq([-0.1])


class TestPercentile:
    def test_linear_interpolation_matches_numpy(self):
        # numpy.percentile([10,20,30,40], 50) == 25.0
        assert percentile([10.0, 20.0, 30.0, 40.0], 50.0) == pytest.approx(25.0)

    def test_unsorted_input_is_handled(self):
        assert percentile([40.0, 10.0, 30.0, 20.0], 50.0) == pytest.approx(25.0)

    def test_p0_is_min_and_p100_is_max(self):
        vals = [5.0, 1.0, 9.0]
        assert percentile(vals, 0.0) == 1.0
        assert percentile(vals, 100.0) == 9.0

    def test_single_value(self):
        assert percentile([7.0], 99.0) == 7.0

    def test_empty_is_zero(self):
        assert percentile([], 50.0) == 0.0

    def test_invalid_pct_rejected(self):
        with pytest.raises(ValueError):
            percentile([1.0], -1.0)
        with pytest.raises(ValueError):
            percentile([1.0], 101.0)

    def test_p50_p99_helpers(self):
        vals = [float(i) for i in range(1, 101)]  # 1..100
        assert p50(vals) == pytest.approx(percentile(vals, 50.0))
        assert p99(vals) == pytest.approx(percentile(vals, 99.0))
