"""Unit tests for app.llm.policy (expected-quality heuristic).

Fully synthetic and pure: no model loading, no network. They pin the
prototype quality bareme of Phase 3 (specialist-on-domain > heavy-generic
> light-generic on a complex intent; light-generic acceptable on simple).
"""
from app.llm.policy import expected_quality
from app.llm.pool import PoolModel

LIGHT = PoolModel(
    model_id="light-generic", tier="light", domain=None, cost=0.0004, latency_ms=300.0
)
HEAVY = PoolModel(
    model_id="heavy-generic", tier="heavy", domain=None, cost=0.018, latency_ms=1200.0
)
SEC = PoolModel(
    model_id="spec-security", tier="heavy", domain="security", cost=0.018, latency_ms=1200.0
)


class TestExpectedQualityBounds:
    def test_always_in_unit_interval(self):
        for model in (LIGHT, HEAVY, SEC):
            for complexity in ("simple", "medium", "complex"):
                for domain in ("ran", "core", "security", "slice"):
                    q = expected_quality(model, complexity, domain)
                    assert 0.0 <= q <= 1.0


class TestOrderingOnComplex:
    def test_specialist_on_domain_beats_heavy_beats_light(self):
        domain = "security"
        q_spec = expected_quality(SEC, "complex", domain)
        q_heavy = expected_quality(HEAVY, "complex", domain)
        q_light = expected_quality(LIGHT, "complex", domain)
        assert q_spec > q_heavy > q_light


class TestLightQualityProfile:
    def test_light_from_measured_table(self):
        # Quality comes straight from the measured per-complexity table
        # (config.QUALITY_LIGHT_BY_COMPLEXITY), not a monotone model.
        for cx in ("simple", "medium", "complex"):
            q = expected_quality(LIGHT, cx, "ran")
            assert 0.0 <= q <= 1.0

    def test_light_decreases_with_complexity(self):
        # The system light (qwen-2.5-72b) has a DECREASING profile: its
        # weakness follows complexity, which is exactly the signal the router
        # exploits (route complex intents to the heavy). A flat light such as
        # deepseek was measured better in absolute terms but made routing
        # useless (cf. ch.5 finding); this test pins the decreasing profile.
        q_simple = expected_quality(LIGHT, "simple", "ran")
        q_medium = expected_quality(LIGHT, "medium", "ran")
        q_complex = expected_quality(LIGHT, "complex", "ran")
        assert q_simple > q_medium > q_complex


class TestSpecialistOffDomain:
    def test_specialist_off_domain_is_worse_than_generic(self):
        # Measured, not assumed (exp_specialist): a RAN framing applied to core
        # intents scored 0.777 against 0.914 for the generic framing. Off-domain
        # specialisation actively hurts; it does not merely forgo the bonus, as
        # the earlier hardcoded constants implied.
        q_off = expected_quality(SEC, "complex", "ran")
        q_heavy = expected_quality(HEAVY, "complex", "ran")
        assert q_off < q_heavy

    def test_off_domain_penalty_exceeds_on_domain_gain(self):
        # The asymmetry is what justifies routing by domain at all: picking the
        # wrong specialist costs 3.6x what picking the right one gains.
        q_on = expected_quality(SEC, "complex", "security")
        q_heavy = expected_quality(HEAVY, "complex", "security")
        q_off = expected_quality(SEC, "complex", "ran")
        assert (q_heavy - q_off) > (q_on - q_heavy)

    def test_specialist_on_domain_better_than_off_domain(self):
        q_on = expected_quality(SEC, "complex", "security")
        q_off = expected_quality(SEC, "complex", "ran")
        assert q_on > q_off
