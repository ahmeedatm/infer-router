"""Frontière de Pareto coût/qualité par balayage du plancher q_min.

Le routeur minimise le coût sous contrainte q >= q_min. En faisant varier un
q_min UNIFORME de 0 à 1, on parcourt tout le spectre entre always-light
(q_min=0, tout au léger) et always-heavy (q_min=1, tout au lourd) : c'est la
frontière de Pareto coût/qualité du système.

Aucun nouvel appel API : les qualités réelles par intent viennent du benchmark
déjà exécuté (stratégies always_light et always_heavy dans benchmark.json). La
DÉCISION à un q_min donné utilise la qualité ATTENDUE du léger (policy, par
complexité) ; la qualité RÉELLE rapportée est celle du modèle effectivement
choisi. Les coûts sont les coûts $ réels moyens par tier (POOL_*_COST).

Sortie : PNG de la frontière + position des 4 stratégies, écrit dans le vault.

Usage :
    .venv/bin/python -m experiments.exp_pareto
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config

BENCH_PATH = Path("experiments/results/benchmark_offline.json")
# Coûts $ réels moyens par appel (mesurés) : cf. config POOL_*_COST.
COST_LIGHT = config.POOL_LIGHT_COST
COST_HEAVY = config.POOL_HEAVY_COST


def _load_per_intent() -> dict[str, dict]:
    """intent_id -> {complexity, q_light, q_heavy} depuis le benchmark."""
    rows = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
    per: dict[str, dict] = {}
    for r in rows:
        d = per.setdefault(r["intent_id"], {"complexity": r["complexity"]})
        if r["strategy"] == "always_light":
            d["q_light"] = r["q"]
        elif r["strategy"] == "always_heavy":
            d["q_heavy"] = r["q"]
    return {k: v for k, v in per.items() if "q_light" in v and "q_heavy" in v}


def _expected_light_quality(complexity: str) -> float:
    """Qualité attendue du léger (policy), base de la DÉCISION de routage."""
    table = config.QUALITY_LIGHT_BY_COMPLEXITY
    return table.get(complexity, table["complex"])


def sweep(per_intent: dict[str, dict], q_min: float) -> tuple[float, float, float]:
    """Route tous les intents à ce q_min uniforme; renvoie (AIQ, coût moyen, %léger).

    Décision par intent : léger si sa qualité attendue (policy, par complexité)
    atteint q_min, sinon lourd. Qualité rapportée = qualité réelle du choisi.
    """
    quals, costs, n_light = [], [], 0
    for d in per_intent.values():
        pick_light = _expected_light_quality(d["complexity"]) >= q_min
        if pick_light:
            quals.append(d["q_light"])
            costs.append(COST_LIGHT)
            n_light += 1
        else:
            quals.append(d["q_heavy"])
            costs.append(COST_HEAVY)
    n = len(per_intent)
    return (sum(quals) / n, sum(costs) / n, 100.0 * n_light / n)


def main() -> None:
    import matplotlib.pyplot as plt

    per = _load_per_intent()
    if not per:
        raise SystemExit("benchmark.json ne contient pas always_light/always_heavy.")

    # Balayage fin du plancher.
    qmins = [i / 100 for i in range(0, 101, 2)]
    frontier = [sweep(per, q) for q in qmins]
    aiqs = [f[0] for f in frontier]
    costs = [f[1] for f in frontier]

    # Points de référence : les deux extrêmes du balayage.
    light_pt = sweep(per, 0.0)      # tout au léger
    heavy_pt = sweep(per, 1.01)     # tout au lourd

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.plot(costs, aiqs, "-o", color="#1f6feb", ms=4, label="frontière (balayage q_min)")
    ax.scatter([light_pt[1]], [light_pt[0]], color="#2e7d32", s=90, zorder=5,
               label=f"Always-Light (AIQ {light_pt[0]:.2f})")
    ax.scatter([heavy_pt[1]], [heavy_pt[0]], color="#5c4db1", s=90, zorder=5,
               label=f"Always-Heavy (AIQ {heavy_pt[0]:.2f})")
    ax.set_xscale("log")
    ax.set_xlabel("coût \$ moyen par intent (échelle log)")
    ax.set_ylabel("AIQ (qualité moyenne réelle, juge)")
    ax.set_title("InferRouter-LLM — frontière de Pareto coût/qualité\n"
                 "(balayage du plancher de qualité q_min, léger qwen-72b vs lourd Opus)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    out = Path("/Users/ahmeedatm/Documents/Vault/Memoire/docs/analyses/"
               "2026-07-22-pareto-cout-qualite.png")
    fig.savefig(out, dpi=150)
    print(f"Écrit : {out}")

    print("\n q_min   AIQ    coût$/intent   %léger")
    for q, (aiq, cost, pl) in zip(qmins, frontier):
        if round(q * 100) % 10 == 0:
            print(f"  {q:.2f}   {aiq:.2f}    {cost:.5f}      {pl:.0f}%")


if __name__ == "__main__":
    main()
