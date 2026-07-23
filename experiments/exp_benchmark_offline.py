"""Benchmark des 4 stratégies reconstruit hors-ligne, sans appel API.

Les qualités, coûts et latences réels de chaque tier sont déjà mesurés :
- léger  (deepseek-v3.2) : calibration_deepseek.json  (q, coût, latence / intent)
- lourd  (claude-opus-4.8) : heavy_robustness.json     (q, coût, latence / intent)

Pour chaque intent commun aux deux, on simule les 4 stratégies (aucun réseau) :
- always_light : toujours le léger,
- always_heavy : toujours le lourd,
- random       : tirage seedé léger/lourd,
- inferrouter  : décision réelle de route() (pure) sur complexité + criticité.

Avantage : gratuit, et checklists homogènes (les mêmes checklists neutres
Sonnet ont servi aux deux calibrations), donc comparaison strictement appariée.

Usage :
    .venv/bin/python -m experiments.exp_benchmark_offline
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from app import config
from app.llm.inferrouter import route
from app.llm.intents import load_intents
from app.llm.metrics import aiq, p50, p99

import os

# Chemin du léger paramétrable : calibration_api_light.json (qwen-72b, défaut,
# le léger du système) ou calibration_deepseek.json (pour l'analyse du finding).
LIGHT_PATH = Path(os.getenv(
    "BENCH_OFFLINE_LIGHT", "experiments/results/calibration_api_light.json"
))
HEAVY_PATH = Path("experiments/results/heavy_robustness.json")
OUT_PATH = Path("experiments/results/benchmark_offline.json")

STRATEGIES = ("always_heavy", "always_light", "random", "inferrouter")


def _load_tiers() -> dict[str, dict]:
    """intent_id -> {complexity, q_light, cost_light, lat_light, q_heavy, ...}."""
    light = {r["intent_id"]: r for r in json.loads(LIGHT_PATH.read_text())}
    heavy = {r["intent_id"]: r for r in json.loads(HEAVY_PATH.read_text())}
    common = sorted(set(light) & set(heavy))
    out = {}
    for iid in common:
        lo, ho = light[iid], heavy[iid]
        out[iid] = {
            "complexity": lo["complexity"],
            "q_light": lo["q_light2"],
            "cost_light": config.POOL_LIGHT_COST,
            "lat_light": lo["latency_light2_ms"],
            "q_heavy": ho["q_heavy_candidate"],
            "cost_heavy": config.POOL_HEAVY_COST,
            "lat_heavy": ho["latency_heavy_candidate_ms"],
        }
    return out


def _choice(strategy, iid, rec, intent, rng):
    """Retourne 'light' ou 'heavy' pour une stratégie sur un intent."""
    if strategy == "always_heavy":
        return "heavy"
    if strategy == "always_light":
        return "light"
    if strategy == "random":
        return rng.choice(("light", "heavy"))
    if strategy == "inferrouter":
        decision = route(
            intent, l_max=1e9, c_max=1e9, complexity=rec["complexity"],
        )
        return "light" if decision.model_id == config.MODEL_LIGHT else "heavy"
    raise ValueError(strategy)


def main() -> None:
    tiers = _load_tiers()
    intents = {it.id: it for it in load_intents(config.DATASET_PATH)}
    records = []
    for strategy in STRATEGIES:
        rng = random.Random(config.BENCH_SEED)
        for iid, rec in tiers.items():
            if iid not in intents:
                continue
            side = _choice(strategy, iid, rec, intents[iid], rng)
            records.append({
                "strategy": strategy,
                "intent_id": iid,
                "complexity": rec["complexity"],
                "tier": side,
                "q": rec[f"q_{side}"],
                "cost": rec[f"cost_{side}"],
                "latency_ms": rec[f"lat_{side}"],
            })
    OUT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    print(f"Benchmark hors-ligne — {len(tiers)} intents, léger={config.MODEL_LIGHT}, "
          f"lourd={config.MODEL_HEAVY}\n")
    print(f"  {'stratégie':14s} {'AIQ':>5s} {'coût $/int':>11s} {'P50 ms':>8s} "
          f"{'P99 ms':>8s}  distribution")
    for strategy in STRATEGIES:
        rows = [r for r in records if r["strategy"] == strategy]
        qs = [r["q"] for r in rows]
        costs = [r["cost"] for r in rows]
        lats = [r["latency_ms"] for r in rows]
        n_light = sum(1 for r in rows if r["tier"] == "light")
        n = len(rows)
        dist = f"{n_light} léger / {n - n_light} lourd"
        print(f"  {strategy:14s} {aiq(qs):>5.2f} {sum(costs)/n:>11.5f} "
              f"{p50(lats):>8.0f} {p99(lats):>8.0f}  {dist}")
    print(f"\nÉcrit : {OUT_PATH}")


if __name__ == "__main__":
    main()
