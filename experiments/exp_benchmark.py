"""Objectif 2 — benchmark des 4 stratégies de routage.

Compare quatre politiques sur le même échantillon d'intents, dans les mêmes
conditions (même ordre, même seed, mêmes modèles cibles) :

  - always_heavy : toujours le tier lourd (qualité max, coût max),
  - always_light : toujours le tier léger (coût min, qualité dégradée),
  - random       : tirage uniforme seedé dans le pool,
  - inferrouter  : la décision tri-critère du système (délègue à route()).

Métriques par stratégie : qualité moyenne (AIQ = q moyen du juge),
coût-proxy agrégé moyen, latence P50/P99, distribution des modèles choisis.

Coût-proxy : temps_inférence (s) × taille_modèle (milliards de paramètres),
cf. config.MODEL_SIZE_B. Le spécialiste "<heavy>#<domain>" partage la taille
et le model_id réseau du heavy de base.

Optimisation de coût : un cache (intent_id, base_model_id) ->
résultat. Si plusieurs stratégies choisissent le même modèle pour le même
intent, on ne l'exécute et ne le juge qu'UNE fois. choose_model et
aggregate_benchmark sont PURES (testables sans réseau). Le runner est
reprenable et écrit de façon incrémentale.

Le tier léger par défaut (config.MODEL_LIGHT) est un modèle LOCAL servi par
Ollama (aucun équivalent hébergé sur OpenRouter au 2026-07-20) : il est routé
vers app.llm.ollama_client plutôt qu'app.llm.openrouter_client (cf.
is_local_model_id). cost_proxy n'en est pas affecté : c'est un proxy de calcul
(temps × taille), pas un prix, donc indépendant de l'hébergement.

Usage :
    SAMPLE_SIZE=2 .venv/bin/python -m experiments.exp_benchmark    # petit
    SAMPLE_SIZE=20 .venv/bin/python -m experiments.exp_benchmark   # complet
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Callable, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from app import config
from app.llm.checklist import generate_checklist
from app.llm.inferrouter import route
from app.llm.intents import load_intents
from app.llm.ollama_client import call_model as call_local_model
from app.llm.judge import judge_rocketeval
from app.llm.metrics import aiq, p50, p99
from app.llm.openrouter_client import call_model as call_api_model
from app.llm.pool import PoolModel, default_pool, generic_pool
from app.llm.prompting import base_model_id, build_prompt, is_local_model_id
from app.llm.schema import Intent

RESULTS_DIR = Path("experiments/results")
# POOL=generic isole l'ablation à deux tiers : même échantillon, même seed,
# seul le pool change, de sorte que l'écart mesuré soit attribuable au pool et
# non à un changement d'intents. Chaque pool écrit son propre fichier pour que
# les deux runs ne se mélangent pas dans le cache de reprise.
_POOL_NAME = os.getenv("POOL", "default")
OUT_PATH = RESULTS_DIR / (
    "benchmark.json" if _POOL_NAME == "default" else f"benchmark_{_POOL_NAME}_pool.json"
)

STRATEGIES: tuple[str, ...] = ("always_heavy", "always_light", "random", "inferrouter")

# Framing et conventions d'id partagés avec le CLI interactif (app.llm.prompting),
# pour que la démo interroge les modèles dans les conditions publiées.
_base_model_id = base_model_id


class Budgets(BaseModel):
    """SLA budgets passés au routeur (latence ms, coût USD/appel)."""

    model_config = ConfigDict(frozen=True)

    l_max: float
    c_max: float


class StrategyError(ValueError):
    """Stratégie de routage inconnue."""


# ── Décision pure : choix du modèle par stratégie ───────────────────────────


def _heavy_id(pool: Sequence[PoolModel]) -> str:
    """Le model_id du heavy générique (tier heavy, domaine None)."""
    for m in pool:
        if m.tier == "heavy" and m.domain is None:
            return m.model_id
    raise StrategyError("No heavy generic model in pool.")


def _light_id(pool: Sequence[PoolModel]) -> str:
    """Le model_id du light générique."""
    for m in pool:
        if m.tier == "light":
            return m.model_id
    raise StrategyError("No light model in pool.")


def choose_model(
    strategy: str,
    intent: Intent,
    pool: Sequence[PoolModel],
    budgets: Budgets,
    rng: random.Random,
    *,
    complexity: str,
) -> Optional[str]:
    """Choisit le model_id servant ``intent`` selon ``strategy`` (pure).

    inferrouter délègue à route() (décision pure quand la complexité est
    fournie : aucun chargement sklearn, aucun réseau). Les autres stratégies
    sont triviales. Renvoie None seulement quand route() ne trouve aucun
    candidat admissible (cas dégénéré ⊥).

    Raises:
        StrategyError: stratégie inconnue.
    """
    if strategy == "always_heavy":
        return _heavy_id(pool)
    if strategy == "always_light":
        return _light_id(pool)
    if strategy == "random":
        return rng.choice([m.model_id for m in pool])
    if strategy == "inferrouter":
        decision = route(
            intent, pool, l_max=budgets.l_max, c_max=budgets.c_max,
            complexity=complexity,
        )
        return decision.model_id
    raise StrategyError(f"Unknown routing strategy: {strategy!r}")


# ── Coût-proxy et exécution avec cache anti-coût ────────────────────────────


def cost_proxy(model_id: str, latency_ms: float) -> float:
    """Coût-proxy : temps_inférence (s) × taille_modèle (milliards).

    Raises:
        StrategyError: taille du modèle absente de la grille (jamais d'estimation
            fabriquée, cf. règles de style).
    """
    base = _base_model_id(model_id)
    size_b = config.MODEL_SIZE_B.get(base)
    if size_b is None:
        raise StrategyError(
            f"Taille (milliards de params) inconnue pour {base!r} ; "
            f"compléter config.MODEL_SIZE_B."
        )
    return (latency_ms / 1000.0) * size_b


def run_with_cache(
    intent_id: str,
    model_id: str,
    execute: Callable[[str, str], dict],
    cache: dict[tuple[str, str], dict],
) -> dict:
    """Exécute (intent, modèle) une seule fois ; sert le cache au rappel.

    La clé de cache est (intent_id, base_model_id) : un spécialiste de domaine
    et le heavy générique partagent le même modèle réseau et donnent donc le
    même résultat, à ne payer qu'une fois.

    Args:
        execute: fonction qui produit le résultat (réseau réel ou stub de test).
        cache: dictionnaire muté de cache (résultats déjà payés).
    """
    key = (intent_id, _base_model_id(model_id))
    if key in cache:
        return cache[key]
    result = execute(intent_id, model_id)
    cache[key] = result
    return result


# ── Agrégation pure des métriques ───────────────────────────────────────────


def _summarize(records: list[dict]) -> dict:
    """Métriques d'une stratégie : AIQ, coût moyen, P50/P99, distribution.

    AIQ et les percentiles de latence viennent de ``app.llm.metrics`` (formules
    du chapitre 3), pour que l'application possède les formules et qu'elles
    soient testées à part.
    """
    n = len(records)
    qs = [r["q"] for r in records]
    costs = [r["cost_proxy"] for r in records]
    latencies = [r["latency_ms"] for r in records]
    distribution: dict[str, int] = {}
    for r in records:
        distribution[r["model_id"]] = distribution.get(r["model_id"], 0) + 1
    return {
        "n": n,
        "aiq": aiq(qs),
        "cost_proxy_mean": sum(costs) / n if n else 0.0,
        "latency_p50_ms": p50(latencies),
        "latency_p99_ms": p99(latencies),
        "distribution": distribution,
    }


def aggregate_benchmark(records: list[dict]) -> dict:
    """Agrège les métriques par stratégie (fonction pure).

    Args:
        records: dicts {strategy, model_id, q, latency_ms, cost_proxy}.

    Returns:
        dict stratégie -> {n, aiq, cost_proxy_mean, latency_p50_ms,
        latency_p99_ms, distribution}. AIQ = qualité moyenne (q du juge).
    """
    by_strategy: dict[str, list[dict]] = {}
    for rec in records:
        by_strategy.setdefault(rec["strategy"], []).append(rec)
    return {strat: _summarize(recs) for strat, recs in by_strategy.items()}


# ── Runner reprenable (appels réseau réels) ─────────────────────────────────


def _make_executor(
    intents_by_id: dict[str, Intent],
    checklist_cache: dict[str, tuple[str, ...]],
) -> Callable[[str, str], dict]:
    """Construit la fonction d'exécution réseau (call_model + juge RocketEval).

    La checklist d'un intent est générée une fois puis réutilisée (cache),
    pour que toutes les réponses d'un même intent soient notées à l'identique.
    """

    def execute(intent_id: str, model_id: str) -> dict:
        intent = intents_by_id[intent_id]
        base = _base_model_id(model_id)
        prompt = build_prompt(intent)
        if is_local_model_id(base):
            resp = call_local_model(
                base, prompt, temperature=0.0, max_tokens=config.RESPONSE_MAX_TOKENS,
            )
        else:
            # Novita rejette qwen2.5-72b-instruct sur cet endpoint (HTTP 400 /
            # réponse sans 'choices', 2026-07-21) ; d'autres fournisseurs le
            # servent sans souci, cf. experiments/exp_calibration_api_light.py.
            resp = call_api_model(
                base, prompt, temperature=0.0, max_tokens=config.RESPONSE_MAX_TOKENS,
                provider={"ignore": ["novita"]},
            )
        if intent_id not in checklist_cache:
            checklist_cache[intent_id] = generate_checklist(intent)
        checklist = checklist_cache[intent_id]
        q = judge_rocketeval(intent, resp.text, checklist=checklist).q
        return {
            "q": q,
            "latency_ms": resp.latency_ms,
            "cost_proxy": cost_proxy(model_id, resp.latency_ms),
            "text": resp.text,
        }

    return execute


def _load_done() -> dict[tuple[str, str], dict]:
    """Records déjà produits, indexés par (intent_id, strategy) — reprise."""
    if not OUT_PATH.exists():
        return {}
    existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {(r["intent_id"], r["strategy"]): r for r in existing}


def _save(records_by_key: dict[tuple[str, str], dict]) -> None:
    """Écriture incrémentale après chaque intent traité."""
    OUT_PATH.write_text(
        json.dumps(list(records_by_key.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _select_intents(
    intents: Sequence[Intent], sample_size: Optional[int]
) -> tuple[Intent, ...]:
    if sample_size is None:
        return tuple(intents)
    import random
    rng = random.Random(42)
    by_cx: dict[str, list[Intent]] = {}
    for it in intents:
        by_cx.setdefault(it.expected_complexity, []).append(it)
    per = max(1, sample_size // len(by_cx)) if by_cx else 0
    out: list[Intent] = []
    for cx in sorted(by_cx):
        pool = sorted(by_cx[cx], key=lambda x: x.id)
        out.extend(rng.sample(pool, min(per, len(pool))))
    return tuple(out[:sample_size])


def run(intents: Sequence[Intent], budgets: Budgets) -> list[dict]:
    """Joue les 4 stratégies sur chaque intent, avec cache anti-coût et reprise.

    Le cache (intent_id, base_model_id) garantit qu'un même modèle sur un même
    intent n'est exécuté/jugé qu'une fois, quel que soit le nombre de stratégies
    qui le choisissent. La complexité est estimée une fois par intent.
    """
    records_by_key = _load_done()
    if records_by_key:
        done_intents = {k[0] for k in records_by_key}
        print(f"Reprise : {len(done_intents)} intent(s) déjà traité(s).\n")

    intents_by_id = {it.id: it for it in intents}
    checklist_cache: dict[str, tuple[str, ...]] = {}
    # Le pool par défaut inclut les 4 spécialistes de domaine, dont la qualité
    # est mesurée depuis exp_specialist. POOL=generic rejoue l'ablation à deux
    # tiers sur le même échantillon, ce qui isole l'effet du pool.
    pool = default_pool() if _POOL_NAME == "default" else generic_pool()
    rng = random.Random(config.BENCH_SEED)

    for i, intent in enumerate(intents, 1):
        if all((intent.id, s) in records_by_key for s in STRATEGIES):
            continue
        print(f"[{i}/{len(intents)}] {intent.id} : routage des 4 stratégies ...", flush=True)
        complexity = _estimate(intent)
        execute = _make_executor(intents_by_id, checklist_cache)
        result_cache: dict[tuple[str, str], dict] = {}
        for strategy in STRATEGIES:
            if (intent.id, strategy) in records_by_key:
                continue
            model_id = choose_model(
                strategy, intent, pool, budgets, rng, complexity=complexity
            )
            if model_id is None:
                records_by_key[(intent.id, strategy)] = _degenerate_record(
                    intent, strategy, complexity
                )
                continue
            outcome = run_with_cache(intent.id, model_id, execute, result_cache)
            records_by_key[(intent.id, strategy)] = {
                "intent_id": intent.id,
                "strategy": strategy,
                "domain": intent.domain,
                "complexity": complexity,
                "model_id": model_id,
                "q": outcome["q"],
                "latency_ms": outcome["latency_ms"],
                "cost_proxy": outcome["cost_proxy"],
            }
        _save(records_by_key)  # incrémental, après chaque intent

    return list(records_by_key.values())


def _degenerate_record(intent: Intent, strategy: str, complexity: str) -> dict:
    """Cas ⊥ : aucun candidat admissible. Consigné, exclu des moyennes en amont."""
    return {
        "intent_id": intent.id,
        "strategy": strategy,
        "domain": intent.domain,
        "complexity": complexity,
        "model_id": None,
        "q": None,
        "latency_ms": None,
        "cost_proxy": None,
        "note": "no admissible model under SLA budgets",
    }


def _estimate(intent: Intent) -> str:
    """Estime la complexité (chargement sklearn paresseux, une fois par intent)."""
    from experiments.train_complexity_estimator import predict_complexity

    return predict_complexity([intent.text])[0]


def _print_table(summary: dict) -> None:
    print("\n=== Benchmark — comparatif des 4 stratégies ===")
    header = f"  {'stratégie':14s} {'n':>3s} {'AIQ':>6s} {'coût(moy)':>10s} {'P50ms':>8s} {'P99ms':>8s}"
    print(header)
    for strat in STRATEGIES:
        s = summary.get(strat)
        if not s:
            continue
        print(
            f"  {strat:14s} {s['n']:>3d} {s['aiq']:>6.2f} "
            f"{s['cost_proxy_mean']:>10.2f} {s['latency_p50_ms']:>8.0f} {s['latency_p99_ms']:>8.0f}"
        )
    infer = summary.get("inferrouter")
    if infer:
        print("\n  Distribution de routing (inferrouter) :")
        for model_id, count in sorted(infer["distribution"].items()):
            pct = 100.0 * count / infer["n"] if infer["n"] else 0.0
            print(f"    {model_id:45s} {count:>3d}  ({pct:.0f}%)")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    intents = load_intents(config.DATASET_PATH)
    sample_env = os.getenv("SAMPLE_SIZE")
    sample_size = int(sample_env) if sample_env else None
    selected = _select_intents(intents, sample_size)
    budgets = Budgets(l_max=config.BENCH_L_MAX_MS, c_max=config.BENCH_C_MAX)

    print(f"Benchmark sur {len(selected)} intent(s)  (seed={config.BENCH_SEED}).")
    print(f"Light={config.MODEL_LIGHT}  Heavy={config.MODEL_HEAVY}")
    print(f"SLA : l_max={budgets.l_max} ms  c_max={budgets.c_max}\n")

    records = run(selected, budgets)
    scored = [r for r in records if r.get("q") is not None]
    summary = aggregate_benchmark(scored)
    _print_table(summary)
    print(f"\nÉcrit : {OUT_PATH}  ({len(records)} records, {len(scored)} notés)")


if __name__ == "__main__":
    main()
