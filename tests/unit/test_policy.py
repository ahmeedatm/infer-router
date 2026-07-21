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


class TestLightOnSimple:
    def test_light_acceptable_on_simple(self):
        q = expected_quality(LIGHT, "simple", "ran")
        assert q >= 0.60

    def test_light_degrades_with_complexity(self):
        q_simple = expected_quality(LIGHT, "simple", "ran")
        q_medium = expected_quality(LIGHT, "medium", "ran")
        q_complex = expected_quality(LIGHT, "complex", "ran")
        assert q_simple > q_medium > q_complex


class TestSpecialistOffDomain:
    def test_specialist_off_domain_no_bonus(self):
        # security specialist on a ran intent behaves like a heavy-generic.
        q_off = expected_quality(SEC, "complex", "ran")
        q_heavy = expected_quality(HEAVY, "complex", "ran")
        assert q_off == q_heavy

    def test_specialist_on_domain_better_than_off_domain(self):
        q_on = expected_quality(SEC, "complex", "security")
        q_off = expected_quality(SEC, "complex", "ran")
        assert q_on > q_off
