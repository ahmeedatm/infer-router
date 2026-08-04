"""Analyses dérivées du benchmark, sans aucun appel payant.

Toutes les mesures de ce script se recalculent à partir d'artefacts déjà
versionnés (``benchmark_offline.json`` pour le pool à deux tiers,
``benchmark_generic_pool.json`` pour l'échantillon de 39 intents,
``specialist_*.json`` pour le cadrage d'expertise). Rien n'appelle un modèle.

Six sorties, chacune répondant à une question que le benchmark brut laisse
ouverte :

1. Intervalles de confiance bootstrap sur les écarts. Les stratégies sont
   comparées sur les mêmes intents, donc les écarts sont appariés et un
   bootstrap sur les différences par intent suffit.
2. Frontière de Pareto complète. Un balayage fin de ``q_min`` révèle tous les
   points de fonctionnement, là où un pas grossier en masque.
3. Comparaison à coût égal contre Random. Le routeur dépense plus que le
   tirage uniforme ; l'écart de qualité brut mélange donc l'effet de la
   décision et celui du budget. On interpole la frontière au coût de Random.
4. Économie en dollars réels sur l'échantillon de 39 intents, dont le
   benchmark d'origine ne rapporte qu'un coût-proxy temps x taille.
5. Point mort de la spécialisation : exactitude minimale du routage par
   domaine au-delà de laquelle un pool de spécialistes cesse de faire perdre.
6. Effet d'un budget de latence resserré : combien d'intents deviennent non
   routables, et à quelle qualité, quand ``L_max`` exclut le tier lourd.

Lancer :  PYTHONPATH=. .venv/bin/python experiments/exp_report_stats.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from app import config
from app.llm.metrics import aiq

RESULTS_DIR = Path("experiments/results")
BENCH_PATH = RESULTS_DIR / "benchmark_offline.json"
SAMPLE39_PATH = RESULTS_DIR / "benchmark_generic_pool.json"
# Real per-intent billed costs, needed because the benchmark's cost field is a
# flat per-tier tariff. The heavy tier is dearer on complex intents, so pricing
# every heavy call at the mean overstates the saving of offloading the simple
# (cheap) ones. These two files carry the actual dollar cost per intent.
HEAVY_COST_PATH = RESULTS_DIR / "heavy_robustness.json"
LIGHT_COST_PATH = RESULTS_DIR / "calibration_api_light.json"
OUT_PATH = RESULTS_DIR / "report_stats.json"
PARETO_PNG = RESULTS_DIR / "pareto_cout_qualite.png"

BOOTSTRAP_DRAWS = 20_000
BOOTSTRAP_SEED = 42
STRATA = ("simple", "medium", "complex")


# ── Chargement ───────────────────────────────────────────────────────────────


def _load_rows(path: Path) -> list[dict]:
    """Read a benchmark result file, failing loudly if it is missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} absent : lancer d'abord la campagne qui le produit."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _by_strategy(rows: Sequence[dict]) -> dict[str, dict[str, dict]]:
    """Index rows as ``{strategy: {intent_id: row}}``."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        out[row["strategy"]][row["intent_id"]] = row
    return dict(out)


# ── 1. Bootstrap apparié ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Interval:
    """A point estimate with its bootstrap confidence interval."""

    estimate: float
    low: float
    high: float

    def as_dict(self) -> dict[str, float]:
        return {"estimate": self.estimate, "ci_low": self.low, "ci_high": self.high}


def bootstrap_mean(
    values: Sequence[float],
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
    level: float = 95.0,
) -> Interval:
    """Bootstrap confidence interval of a mean.

    Args:
        values: Sample values (per-intent qualities, or per-intent differences
            when the comparison is paired).
        draws: Number of resamples.
        seed: Seed of the resampling generator, fixed for reproducibility.
        level: Confidence level in percent.

    Returns:
        The sample mean and its percentile interval.

    Raises:
        ValueError: if ``values`` is empty or ``level`` is outside ]0, 100[.
    """
    if not len(values):
        raise ValueError("bootstrap_mean sur un échantillon vide.")
    if not 0.0 < level < 100.0:
        raise ValueError(f"level doit être dans ]0, 100[, reçu {level}.")
    sample = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = rng.choice(sample, size=(draws, sample.size), replace=True).mean(axis=1)
    tail = (100.0 - level) / 2.0
    return Interval(
        estimate=float(sample.mean()),
        low=float(np.percentile(means, tail)),
        high=float(np.percentile(means, 100.0 - tail)),
    )


def paired_differences(
    indexed: dict[str, dict[str, dict]], left: str, right: str, key: str = "q"
) -> np.ndarray:
    """Per-intent difference ``left - right`` over the intents both share."""
    shared = sorted(set(indexed[left]) & set(indexed[right]))
    if not shared:
        raise ValueError(f"Aucun intent commun entre {left} et {right}.")
    return np.array(
        [indexed[left][i][key] - indexed[right][i][key] for i in shared], dtype=float
    )


# ── 2-3. Frontière de Pareto et comparaison à coût égal ──────────────────────


@dataclass(frozen=True)
class FrontierPoint:
    """One operating point of the router: a floor, its cost and its quality."""

    q_min: float
    cost: float
    quality: float
    n_light: int


def pareto_frontier(
    complexities: Sequence[str],
    q_light: Sequence[float],
    q_heavy: Sequence[float],
    step: float = 0.01,
    cost_light: Optional[Sequence[float]] = None,
    cost_heavy: Optional[Sequence[float]] = None,
) -> tuple[FrontierPoint, ...]:
    """Sweep the quality floor and keep every distinct operating point.

    The router sends an intent to the light tier when the light tier's
    *expected* quality at that complexity clears the floor. Sweeping the floor
    from 0 to 1 therefore walks the whole spectrum from all-light to all-heavy.
    A coarse sweep hides operating points, so the step defaults to 0.01.

    Cost is the **real per-intent** price when ``cost_light`` / ``cost_heavy``
    are given (billed dollars from the campaign), so the frontier reflects that
    the heavy tier is dearer on complex intents than on simple ones. When they
    are omitted, the flat per-tier tariff from config is used (kept for the
    unit tests, which do not need real costs).

    Args:
        complexities: Annotated complexity of each intent.
        q_light: Measured quality of the light tier, per intent.
        q_heavy: Measured quality of the heavy tier, per intent.
        step: Granularity of the floor sweep.
        cost_light: Real per-intent cost on the light tier, or ``None``.
        cost_heavy: Real per-intent cost on the heavy tier, or ``None``.

    Returns:
        Distinct operating points, ordered by increasing cost.
    """
    expected = config.QUALITY_LIGHT_BY_COMPLEXITY
    light = np.asarray(q_light, dtype=float)
    heavy = np.asarray(q_heavy, dtype=float)
    n = len(complexities)
    cl = (
        np.asarray(cost_light, dtype=float)
        if cost_light is not None
        else np.full(n, config.POOL_LIGHT_COST)
    )
    cheavy = (
        np.asarray(cost_heavy, dtype=float)
        if cost_heavy is not None
        else np.full(n, config.POOL_HEAVY_COST)
    )
    seen: dict[tuple[int, ...], FrontierPoint] = {}
    for floor in np.arange(0.0, 1.0 + step / 2, step):
        to_light = tuple(
            1 if expected.get(c, expected["complex"]) >= floor else 0
            for c in complexities
        )
        if to_light in seen:
            continue
        mask = np.array(to_light) == 1
        chosen = np.where(mask, light, heavy)
        cost = float(np.mean(np.where(mask, cl, cheavy)))
        seen[to_light] = FrontierPoint(
            q_min=float(floor),
            cost=cost,
            quality=float(aiq(chosen.tolist())),
            n_light=int(sum(to_light)),
        )
    return tuple(sorted(seen.values(), key=lambda p: p.cost))


def quality_at_cost(frontier: Sequence[FrontierPoint], cost: float) -> float:
    """Quality the frontier delivers at a given budget, by linear interpolation.

    Between two operating points the router can reach any intermediate budget
    by mixing them, so the segment joining them is attainable. Interpolating is
    therefore the fair way to compare a router against a fixed strategy that
    happens to sit between two of its operating points.
    """
    costs = [p.cost for p in frontier]
    qualities = [p.quality for p in frontier]
    return float(np.interp(cost, costs, qualities))


# ── 5. Point mort de la spécialisation ───────────────────────────────────────


def specialisation_break_even(on_domain_gain: float, off_domain_loss: float) -> float:
    """Domain-routing accuracy above which a specialist pool stops losing.

    A specialist earns ``on_domain_gain`` when the domain is right and costs
    ``off_domain_loss`` (a positive magnitude) when it is wrong. With accuracy
    ``a`` the expected delta is ``a * gain - (1 - a) * loss``, which is null at
    ``loss / (gain + loss)``.

    Raises:
        ValueError: if either magnitude is negative, or both are zero.
    """
    if on_domain_gain < 0 or off_domain_loss < 0:
        raise ValueError("gain et perte doivent être exprimés en magnitudes >= 0.")
    total = on_domain_gain + off_domain_loss
    if total == 0:
        raise ValueError("gain et perte nuls : pas de point mort défini.")
    return off_domain_loss / total


def expected_specialisation_delta(
    accuracy: float, on_domain_gain: float, off_domain_loss: float
) -> float:
    """Expected quality delta of a specialist pool at a given routing accuracy."""
    if not 0.0 <= accuracy <= 1.0:
        raise ValueError(f"accuracy doit être dans [0, 1], reçu {accuracy}.")
    return accuracy * on_domain_gain - (1.0 - accuracy) * off_domain_loss


# ── 6. Budget de latence resserré ────────────────────────────────────────────


@dataclass(frozen=True)
class SlaOutcome:
    """What a hard latency budget does to a benchmark run."""

    l_max_ms: float
    n_unroutable: int
    n_forced_light: int
    quality: Optional[float]
    cost: Optional[float]


def tighten_latency(
    indexed: dict[str, dict[str, dict]],
    l_max_ms: float,
    cost_light: Optional[dict[str, float]] = None,
    cost_heavy: Optional[dict[str, float]] = None,
) -> SlaOutcome:
    """Re-decide every intent under a hard latency budget.

    Admissibility is evaluated on the latency each tier actually took on that
    intent, as measured during the campaign. An intent whose every candidate
    breaches the budget is unroutable (bottom); the router's choice is kept
    when it fits, otherwise the intent falls back to the only admissible tier.

    ``n_forced_light`` counts *only* fallbacks that land on the light tier
    (router chose heavy, heavy breached, light fits), matching the report's
    column "rabattus sur le léger". Fallbacks onto the heavy tier (router chose
    light, light breached) are not counted there.

    Cost is the real per-intent billed cost when ``cost_light`` / ``cost_heavy``
    are given, else the flat per-tier ``cost`` field of the rows (kept for the
    unit tests). Quality and cost are averaged over the routable intents only.
    """
    if l_max_ms <= 0:
        raise ValueError(f"l_max_ms doit être > 0, reçu {l_max_ms}.")
    shared = sorted(set(indexed["inferrouter"]) & set(indexed["always_light"]))
    kept_q: list[float] = []
    kept_cost: list[float] = []
    unroutable = 0
    forced_light = 0
    for intent_id in shared:
        light = indexed["always_light"][intent_id]
        heavy = indexed["always_heavy"][intent_id]
        light_ok = light["latency_ms"] <= l_max_ms
        heavy_ok = heavy["latency_ms"] <= l_max_ms
        if not (light_ok or heavy_ok):
            unroutable += 1
            continue
        chosen_tier = indexed["inferrouter"][intent_id]["tier"]
        if chosen_tier == "light" and light_ok:
            tier = "light"
        elif chosen_tier == "heavy" and heavy_ok:
            tier = "heavy"
        else:
            # The chosen tier breached; only the other tier is admissible.
            tier = "light" if light_ok else "heavy"
            if tier == "light" and chosen_tier == "heavy":
                forced_light += 1
        if tier == "light":
            kept_q.append(light["q"])
            kept_cost.append(
                cost_light[intent_id] if cost_light is not None else light["cost"]
            )
        else:
            kept_q.append(heavy["q"])
            kept_cost.append(
                cost_heavy[intent_id] if cost_heavy is not None else heavy["cost"]
            )
    return SlaOutcome(
        l_max_ms=l_max_ms,
        n_unroutable=unroutable,
        n_forced_light=forced_light,
        quality=float(np.mean(kept_q)) if kept_q else None,
        cost=float(np.mean(kept_cost)) if kept_cost else None,
    )


# ── Figure ───────────────────────────────────────────────────────────────────


def _plot_frontier(
    frontier: Sequence[FrontierPoint],
    n_intents: int,
    path: Path,
) -> None:
    """Draw the real-cost quality frontier (frontier only).

    Random is deliberately not plotted: at real per-intent cost it sits above
    the frontier at its own budget (an uninformed split is cheaper on average,
    because it does not concentrate the expensive complex intents on the heavy
    tier), and the equal-budget reading it invited was dropped from the report
    as an over-engineered construction. The bare frontier is what the thesis
    now shows.

    Imported lazily: matplotlib is heavy and only this function needs it.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    costs = [p.cost for p in frontier]
    qualities = [p.quality for p in frontier]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.plot(costs, qualities, marker="o", color="#b00020", linewidth=1.6, zorder=3)
    for point in frontier:
        offset = (-58, -14) if point.n_light == 0 else (8, -13)
        ax.annotate(
            f"{point.n_light}/{n_intents} au léger",
            (point.cost, point.quality),
            textcoords="offset points",
            xytext=offset,
            fontsize=7.5,
            color="#444444",
        )
    ax.set_xlabel("Coût réel moyen par intent (USD)")
    ax.set_ylabel("Qualité agrégée (AIQ)")
    ax.grid(True, linewidth=0.4, alpha=0.5)
    ax.set_ylim(0.35, 0.95)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ── Rapport ──────────────────────────────────────────────────────────────────


def main() -> None:
    rows = _load_rows(BENCH_PATH)
    indexed = _by_strategy(rows)
    ids = sorted(indexed["inferrouter"])
    complexities = [indexed["inferrouter"][i]["complexity"] for i in ids]
    q_light = [indexed["always_light"][i]["q"] for i in ids]
    q_heavy = [indexed["always_heavy"][i]["q"] for i in ids]

    # Real per-intent billed costs (see the constants' rationale).
    real_heavy = {r["intent_id"]: r["cost_heavy_candidate"] for r in _load_rows(HEAVY_COST_PATH)}
    real_light = {r["intent_id"]: r["cost_light2"] for r in _load_rows(LIGHT_COST_PATH)}
    cost_light = [real_light[i] for i in ids]
    cost_heavy = [real_heavy[i] for i in ids]

    print(f"Benchmark à deux tiers — {len(ids)} intents\n")

    # 0. Économie : distinguer la réduction d'appels lourds de la dépense réelle.
    tiers = [indexed["inferrouter"][i]["tier"] for i in ids]
    n_heavy_calls = sum(1 for t in tiers if t == "heavy")
    call_reduction = 1.0 - n_heavy_calls / len(ids)
    spend_ir = float(np.mean([
        real_heavy[i] if t == "heavy" else real_light[i]
        for i, t in zip(ids, tiers)
    ]))
    spend_ah = float(np.mean(cost_heavy))
    print("0. Économie")
    print(f"   appels lourds en moins   {call_reduction * 100:.1f} %")
    print(f"   dépense réelle vs AH     {(1 - spend_ir / spend_ah) * 100:.1f} %"
          f"  (InferRouter {spend_ir:.4f} vs {spend_ah:.4f} $/intent)")

    # 1. Intervalles de confiance.
    print("1. Intervalles de confiance (bootstrap apparié, 20 000 tirages)")
    aiq_router = bootstrap_mean([indexed["inferrouter"][i]["q"] for i in ids])
    gain_random = bootstrap_mean(paired_differences(indexed, "inferrouter", "random"))
    loss_heavy = bootstrap_mean(
        paired_differences(indexed, "inferrouter", "always_heavy")
    )
    for label, interval in (
        ("AIQ InferRouter-LLM", aiq_router),
        ("écart sur Random", gain_random),
        ("écart sur Always-Heavy", loss_heavy),
    ):
        print(
            f"   {label:24s} {interval.estimate:+.3f}  "
            f"IC95 [{interval.low:+.3f} ; {interval.high:+.3f}]"
        )

    # 2. Frontière complète, en coût réel par intent.
    frontier = pareto_frontier(
        complexities, q_light, q_heavy,
        cost_light=cost_light, cost_heavy=cost_heavy,
    )
    print(f"\n2. Frontière de Pareto — {len(frontier)} points de fonctionnement")
    for point in frontier:
        print(
            f"   q_min <= {point.q_min:.2f}   coût {point.cost:.5f}   "
            f"AIQ {point.quality:.3f}   {point.n_light} intents au léger"
        )

    # 3. Comparaison à coût réel égal contre Random. En coût réel, Random est
    #    plus économe qu'un point de frontière de même fraction (il ne
    #    concentre pas les intents complexes, chers, sur le lourd), donc à son
    #    propre budget la frontière passe SOUS lui. Le rapport a retiré cette
    #    analyse ; on la garde ici, chiffrée, pour tracer d'où vient le −0,040.
    cost_random = float(np.mean([
        real_heavy[i] if indexed["random"][i]["tier"] == "heavy" else real_light[i]
        for i in ids
    ]))
    q_random = float(aiq([indexed["random"][i]["q"] for i in ids]))
    q_frontier = quality_at_cost(frontier, cost_random)
    print("\n3. Comparaison à coût réel égal contre Random")
    print(f"   coût réel de Random      {cost_random:.5f} $/intent")
    print(f"   frontière à ce coût      AIQ {q_frontier:.3f}")
    print(f"   Random                   AIQ {q_random:.3f}")
    print(f"   écart à budget réel égal {q_frontier - q_random:+.3f}")

    # 4. Échantillon de 39 intents : on ne rapporte que le taux de routage vers
    #    le léger. Seuls 24 des 39 ont un coût réel par intent (jeu partiel), la
    #    dépense réelle n'y est donc pas calculable ; l'économie suit ce taux.
    sample = _by_strategy(_load_rows(SAMPLE39_PATH))
    sample_ids = sorted(sample["inferrouter"])
    n_light = sum(
        1
        for i in sample_ids
        if sample["inferrouter"][i]["model_id"] == config.MODEL_LIGHT
    )
    n_heavy = len(sample_ids) - n_light
    light_rate = n_light / len(sample_ids)
    print(f"\n4. Échantillon de {len(sample_ids)} intents")
    print(f"   {n_light} au léger, {n_heavy} au lourd")
    print(f"   part déportée vers le léger  {light_rate * 100:.1f} %")

    # 5. Point mort de la spécialisation.
    gain = config.SPECIALIST_ON_DOMAIN_DELTA
    loss = abs(config.SPECIALIST_OFF_DOMAIN_DELTA)
    break_even = specialisation_break_even(gain, loss)
    print("\n5. Spécialisation par domaine")
    print(f"   gain sur domaine {gain:+.3f}, perte hors domaine {-loss:+.3f}")
    print(f"   point mort du routage par domaine  {break_even * 100:.1f} %")
    for accuracy in (0.817, 0.90, 1.00):
        delta = expected_specialisation_delta(accuracy, gain, loss)
        print(f"   à {accuracy * 100:5.1f} % d'exactitude : delta attendu {delta:+.3f}")

    # 6. Budget de latence resserré, en coût réel par intent.
    print("\n6. Effet d'un budget de latence dur")
    sla_rows = []
    for budget in (30_000.0, 20_000.0, 10_000.0, 5_000.0):
        outcome = tighten_latency(indexed, budget, real_light, real_heavy)
        sla_rows.append(outcome)
        quality = "n/a" if outcome.quality is None else f"{outcome.quality:.3f}"
        cost = "n/a" if outcome.cost is None else f"{outcome.cost:.5f}"
        print(
            f"   L_max {budget / 1000:5.0f} s : {outcome.n_unroutable:2d} non routables, "
            f"{outcome.n_forced_light:2d} rabattus sur le léger, "
            f"AIQ {quality}, coût {cost}"
        )

    _plot_frontier(frontier, len(ids), PARETO_PNG)
    print(f"\nFigure écrite : {PARETO_PNG}")

    report = {
        "n_intents": len(ids),
        "economy": {
            "heavy_call_reduction": call_reduction,
            "real_spend_reduction_vs_ah": 1 - spend_ir / spend_ah,
            "spend_inferrouter": spend_ir,
            "spend_always_heavy": spend_ah,
        },
        "confidence_intervals": {
            "aiq_inferrouter": aiq_router.as_dict(),
            "delta_vs_random": gain_random.as_dict(),
            "delta_vs_always_heavy": loss_heavy.as_dict(),
        },
        "pareto_frontier": [
            {
                "q_min_max": p.q_min,
                "cost": p.cost,
                "aiq": p.quality,
                "n_light": p.n_light,
            }
            for p in frontier
        ],
        "equal_real_cost_vs_random": {
            "cost": cost_random,
            "aiq_frontier": q_frontier,
            "aiq_random": q_random,
            "delta": q_frontier - q_random,
        },
        "sample39": {
            "n_intents": len(sample_ids),
            "n_light": n_light,
            "n_heavy": n_heavy,
            "light_routing_rate": light_rate,
        },
        "specialisation": {
            "on_domain_gain": gain,
            "off_domain_loss": -loss,
            "break_even_accuracy": break_even,
            "expected_delta_at_817": expected_specialisation_delta(0.817, gain, loss),
        },
        "hard_latency_budget": [
            {
                "l_max_ms": o.l_max_ms,
                "n_unroutable": o.n_unroutable,
                "n_forced_light": o.n_forced_light,
                "aiq": o.quality,
                "cost": o.cost,
            }
            for o in sla_rows
        ],
    }
    OUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Rapport écrit : {OUT_PATH}")


if __name__ == "__main__":
    main()
