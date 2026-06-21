"""Unit tests for app.llm.inferrouter (tri-criteria routing decision).

Pure tests: complexity is always passed explicitly, so the sklearn model is
never loaded and no network/Ollama call happens. They check that the
orchestrator wires the pool, the policy and router.select correctly, and
emits a coherent RouteDecision (including the degenerate no-admissible case).
"""
from app.config import (
    MODEL_LIGHT,
    POOL_HEAVY_COST,
    POOL_HEAVY_LATENCY_MS,
    POOL_LIGHT_COST,
    POOL_LIGHT_LATENCY_MS,
)
from app.llm.inferrouter import RouteDecision, route
from app.llm.pool import default_pool
from app.llm.schema import Intent


def _intent(domain: str, complexity: str, criticality: str = "med") -> Intent:
    return Intent(
        id=f"i-{domain}-{complexity}",
        text=f"a {complexity} {domain} intent",
        domain=domain,
        expected_complexity=complexity,
        criticality=criticality,
    )


class TestRouteDecisionShape:
    def test_returns_route_decision(self):
        intent = _intent("ran", "simple")
        decision = route(intent, l_max=10_000.0, c_max=10.0, complexity="simple")
        assert isinstance(decision, RouteDecision)
        assert decision.complexity == "simple"
        assert decision.admissible_count == len(default_pool())

    def test_is_frozen(self):
        import pytest
        from pydantic import ValidationError

        intent = _intent("ran", "simple")
        decision = route(intent, l_max=10_000.0, c_max=10.0, complexity="simple")
        with pytest.raises(ValidationError):
            decision.model_id = "x"


class TestSimpleSmallBudget:
    def test_simple_intent_tight_budget_picks_light(self):
        # Budget admits the light tier only -> light wins.
        intent = _intent("ran", "simple")
        decision = route(
            intent,
            l_max=POOL_LIGHT_LATENCY_MS,
            c_max=POOL_LIGHT_COST,
            complexity="simple",
        )
        assert decision.model_id == MODEL_LIGHT
        assert "light generic" in decision.rationale
        assert decision.admissible_count == 1


class TestComplexSecurityLargeBudget:
    def test_complex_security_large_budget_picks_specialist(self):
        intent = _intent("security", "complex", criticality="high")
        decision = route(
            intent,
            l_max=POOL_HEAVY_LATENCY_MS,
            c_max=POOL_HEAVY_COST,
            complexity="complex",
        )
        assert decision.model_id is not None
        assert "security" in decision.model_id
        assert "security" in decision.rationale


class TestDegenerate:
    def test_latency_too_tight_returns_none(self):
        intent = _intent("ran", "simple")
        decision = route(intent, l_max=1.0, c_max=10.0, complexity="simple")
        assert decision.model_id is None
        assert decision.admissible_count == 0
        assert "no admissible" in decision.rationale.lower()


class TestRationale:
    def test_rationale_mentions_complexity_and_domain(self):
        intent = _intent("core", "complex")
        decision = route(
            intent,
            l_max=POOL_HEAVY_LATENCY_MS,
            c_max=POOL_HEAVY_COST,
            complexity="complex",
        )
        assert "complex" in decision.rationale
        assert "core" in decision.rationale
