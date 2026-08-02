"""Tests des fonctions pures du benchmark des 4 stratégies (objectif 2).

choose_model est pure (pas de réseau) : pour inferrouter elle délègue à
route() (décision pure quand la complexité est fournie). aggregate_benchmark
calcule par stratégie : qualité moyenne (AIQ), coût-proxy agrégé moyen,
latence P50/P99 et distribution des modèles choisis. Le cache anti-coût est
testé via un compteur d'appels : deux stratégies qui choisissent le même
modèle pour le même intent ne doivent l'exécuter/juger qu'une fois.
"""
from __future__ import annotations

import random

from app.config import (
    MODEL_HEAVY,
    MODEL_LIGHT,
    POOL_LIGHT_COST,
    POOL_LIGHT_LATENCY_MS,
)
from app.llm.pool import default_pool, generic_pool
from app.llm.schema import Intent
from experiments.exp_benchmark import (
    Budgets,
    aggregate_benchmark,
    choose_model,
    is_local_model_id,
    run_with_cache,
)


class TestIsLocalModelId:
    def test_ollama_tag_is_local(self):
        assert is_local_model_id("qwen2.5:14b-instruct") is True

    def test_openrouter_id_is_not_local(self):
        assert is_local_model_id("anthropic/claude-sonnet-4.6") is False

    def test_domain_suffixed_openrouter_id_is_not_local(self):
        # is_local_model_id reçoit déjà le model_id sans suffixe de domaine
        # (appelé sur _base_model_id(model_id) dans l'exécuteur) ; testé ici
        # sur l'id brut pour vérifier qu'un '#' seul ne déclenche pas '":"'.
        assert is_local_model_id("anthropic/claude-sonnet-4.6#ran") is False


def _intent(domain="ran", complexity="simple", criticality="med"):
    return Intent(
        id=f"i-{domain}-{complexity}",
        text=f"a {complexity} {domain} intent",
        domain=domain,
        expected_complexity=complexity,
        criticality=criticality,
    )


_WIDE = Budgets(l_max=1e9, c_max=1e9)


class TestChooseModel:
    def test_always_heavy_picks_heavy(self):
        m = choose_model(
            "always_heavy", _intent(), default_pool(), _WIDE,
            random.Random(0), complexity="simple",
        )
        assert m == MODEL_HEAVY

    def test_always_light_picks_light(self):
        m = choose_model(
            "always_light", _intent(), default_pool(), _WIDE,
            random.Random(0), complexity="complex",
        )
        assert m == MODEL_LIGHT

    def test_random_is_seeded_deterministic(self):
        pool = default_pool()
        a = choose_model(
            "random", _intent(), pool, _WIDE, random.Random(123), complexity="simple",
        )
        b = choose_model(
            "random", _intent(), pool, _WIDE, random.Random(123), complexity="simple",
        )
        assert a == b
        assert a in {m.model_id for m in pool}

    def test_random_varies_across_seeds(self):
        pool = default_pool()
        picks = {
            choose_model(
                "random", _intent(), pool, _WIDE, random.Random(s), complexity="simple",
            )
            for s in range(20)
        }
        assert len(picks) > 1  # le tirage explore plusieurs modèles

    def test_inferrouter_delegates_to_route_tight_budget(self):
        # Budget admettant seulement le light -> route() choisit le light.
        tight = Budgets(l_max=POOL_LIGHT_LATENCY_MS, c_max=POOL_LIGHT_COST)
        m = choose_model(
            "inferrouter", _intent("ran", "simple"), default_pool(), tight,
            random.Random(0), complexity="simple",
        )
        assert m == MODEL_LIGHT

    def test_inferrouter_simple_med_picks_light_for_cost(self):
        # simple + med (q_min=0.50): light (0.64) clears the floor and is
        # cheapest -> chosen over the heavy, per the cost-minimising objective.
        m = choose_model(
            "inferrouter", _intent("ran", "simple"), generic_pool(),
            _WIDE, random.Random(0), complexity="simple",
        )
        assert m == MODEL_LIGHT

    def test_inferrouter_complex_med_falls_back_to_heavy(self):
        # complex + med (q_min=0.50): the decreasing light (qwen 0.32 on
        # complex) is below the floor, so the heavy is chosen. The router
        # exploits the light's complexity-dependent weakness.
        m = choose_model(
            "inferrouter", _intent("security", "complex"), generic_pool(),
            _WIDE, random.Random(0), complexity="complex",
        )
        assert m == MODEL_HEAVY

    def test_inferrouter_simple_med_stays_light(self):
        # simple + med (q_min=0.50): the light is strong on simple (qwen 0.64),
        # clears the floor, and is cheapest -> kept.
        m = choose_model(
            "inferrouter", _intent("ran", "simple"), generic_pool(),
            _WIDE, random.Random(0), complexity="simple",
        )
        assert m == MODEL_LIGHT

    def test_unknown_strategy_raises(self):
        import pytest

        with pytest.raises(ValueError):
            choose_model(
                "nope", _intent(), default_pool(), _WIDE,
                random.Random(0), complexity="simple",
            )


class TestRunWithCache:
    def test_same_model_same_intent_executed_once(self):
        calls: list[tuple[str, str]] = []

        def fake_execute(intent_id, model_id):
            calls.append((intent_id, model_id))
            return {"q": 0.9, "latency_ms": 100.0, "cost_proxy": 1.0}

        cache: dict[tuple[str, str], dict] = {}
        # always_heavy et inferrouter choisissent toutes deux le heavy ici.
        run_with_cache("i1", MODEL_HEAVY, fake_execute, cache)
        run_with_cache("i1", MODEL_HEAVY, fake_execute, cache)
        assert calls == [("i1", MODEL_HEAVY)]  # un seul appel réel

    def test_different_model_or_intent_executes_again(self):
        calls: list[tuple[str, str]] = []

        def fake_execute(intent_id, model_id):
            calls.append((intent_id, model_id))
            return {"q": 0.5, "latency_ms": 10.0, "cost_proxy": 2.0}

        cache: dict[tuple[str, str], dict] = {}
        run_with_cache("i1", MODEL_LIGHT, fake_execute, cache)
        run_with_cache("i1", MODEL_HEAVY, fake_execute, cache)  # autre modèle
        run_with_cache("i2", MODEL_LIGHT, fake_execute, cache)  # autre intent
        assert len(calls) == 3


class TestAggregateBenchmark:
    def _rec(self, strategy, model_id, q, latency_ms, cost_proxy):
        return {
            "strategy": strategy,
            "model_id": model_id,
            "q": q,
            "latency_ms": latency_ms,
            "cost_proxy": cost_proxy,
        }

    def test_aiq_cost_and_distribution(self):
        records = [
            self._rec("always_light", MODEL_LIGHT, 0.6, 100.0, 1.0),
            self._rec("always_light", MODEL_LIGHT, 0.8, 200.0, 2.0),
            self._rec("always_heavy", MODEL_HEAVY, 0.95, 1000.0, 50.0),
        ]
        out = aggregate_benchmark(records)
        light = out["always_light"]
        assert abs(light["aiq"] - 0.7) < 1e-9          # (0.6+0.8)/2
        assert abs(light["cost_proxy_mean"] - 1.5) < 1e-9
        assert light["n"] == 2
        assert light["distribution"] == {MODEL_LIGHT: 2}
        assert out["always_heavy"]["distribution"] == {MODEL_HEAVY: 1}

    def test_latency_percentiles(self):
        # 100 valeurs 1..100 : P50 ~ 50.5 (interpolation), P99 ~ 99.01.
        records = [
            self._rec("s", "m", 1.0, float(v), 1.0) for v in range(1, 101)
        ]
        out = aggregate_benchmark(records)["s"]
        assert 49.0 <= out["latency_p50_ms"] <= 52.0
        assert 98.0 <= out["latency_p99_ms"] <= 100.0

    def test_distribution_counts_multiple_models(self):
        records = [
            self._rec("inferrouter", MODEL_LIGHT, 0.7, 100.0, 1.0),
            self._rec("inferrouter", MODEL_LIGHT, 0.7, 100.0, 1.0),
            self._rec("inferrouter", f"{MODEL_HEAVY}#ran", 0.9, 900.0, 40.0),
        ]
        dist = aggregate_benchmark(records)["inferrouter"]["distribution"]
        assert dist[MODEL_LIGHT] == 2
        assert dist[f"{MODEL_HEAVY}#ran"] == 1

    def test_empty_records(self):
        assert aggregate_benchmark([]) == {}
