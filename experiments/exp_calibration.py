"""Objectif 1 — calibration de la qualité réelle.

Pour chaque intent de l'échantillon : exécute le tier LIGHT et le tier HEAVY
(via OpenRouter), génère UNE checklist RocketEval propre à l'intent, puis note
les DEUX réponses avec cette même checklist (juge local Ollama). On obtient la
qualité réelle q par tier, qu'on agrège en une matrice tier×complexité et un
écart heavy-light par complexité.

C'est cette matrice qui calibre l'heuristique `expected_quality` (app/llm/
policy.py) et qui éclaire la prémisse du routage : sur les intents simples, le
light suffit-il ? (écart heavy-light négligeable).

`aggregate_quality` est PURE (testable sans réseau). Le runner est reprenable
et écrit de façon incrémentale dans experiments/results/calibration.json :
une interruption ne fait pas repayer les intents déjà traités.

Pour limiter les appels API : valider sur un petit échantillon avant le run
complet via SAMPLE_SIZE.

Usage :
    SAMPLE_SIZE=2 .venv/bin/python -m experiments.exp_calibration   # petit
    SAMPLE_SIZE=20 .venv/bin/python -m experiments.exp_calibration  # complet
    SUBSET=core-read-amf-registrations,ran-read-prb-utilization \
        .venv/bin/python -m experiments.exp_calibration            # ciblé
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Sequence

from app import config
from app.llm.checklist import generate_checklist
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval
from app.llm.openrouter_client import call_model
from app.llm.schema import Intent

RESULTS_DIR = Path("experiments/results")
OUT_PATH = RESULTS_DIR / "calibration.json"

_COMPLEXITY_ORDER = ("simple", "medium", "complex")

SYSTEM_PREFIX = (
    "You are a network operations assistant for a 5G/O-RAN operator. "
    "Answer the following operator intent precisely and concisely.\n\nIntent: "
)


# ── Fonction pure : agrégation de la qualité réelle ─────────────────────────


def _mean(values: Sequence[float]) -> float:
    """Moyenne, 0.0 sur une suite vide (évite la division par zéro)."""
    return sum(values) / len(values) if values else 0.0


def aggregate_quality(records: list[dict]) -> dict:
    """Agrège la qualité réelle du juge par tier et par complexité (pure).

    Args:
        records: dicts {intent_id, complexity, q_light, q_heavy}. Les entrées
            en erreur (sans q_light/q_heavy) doivent être filtrées en amont.

    Returns:
        dict avec :
        - "matrix"[complexity][tier]  : q moyen (tier ∈ {light, heavy}),
        - "gap"[complexity]           : q_heavy_moyen - q_light_moyen,
        - "n"[complexity]             : nb d'intents de cette complexité,
        - "overall"                   : {light, heavy, gap} globaux.
        Une complexité absente des données n'apparaît dans aucune sous-clé.
    """
    by_level: dict[str, dict[str, list[float]]] = {}
    for rec in records:
        level = rec["complexity"]
        bucket = by_level.setdefault(level, {"light": [], "heavy": []})
        bucket["light"].append(rec["q_light"])
        bucket["heavy"].append(rec["q_heavy"])

    matrix: dict[str, dict[str, float]] = {}
    gap: dict[str, float] = {}
    counts: dict[str, int] = {}
    for level, bucket in by_level.items():
        light_mean = _mean(bucket["light"])
        heavy_mean = _mean(bucket["heavy"])
        matrix[level] = {"light": light_mean, "heavy": heavy_mean}
        gap[level] = heavy_mean - light_mean
        counts[level] = len(bucket["light"])

    all_light = [r["q_light"] for r in records]
    all_heavy = [r["q_heavy"] for r in records]
    overall = {
        "light": _mean(all_light),
        "heavy": _mean(all_heavy),
        "gap": _mean(all_heavy) - _mean(all_light),
    }
    return {"matrix": matrix, "gap": gap, "n": counts, "overall": overall}


# ── Runner reprenable (appels réseau réels) ─────────────────────────────────


def build_prompt(intent: Intent) -> str:
    return f"{SYSTEM_PREFIX}{intent.text}"


def _load_done() -> dict[str, dict]:
    """Records déjà calibrés, indexés par intent_id (reprise après crash)."""
    if not OUT_PATH.exists():
        return {}
    existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {r["intent_id"]: r for r in existing}


def _save(records_by_id: dict[str, dict]) -> None:
    """Écriture incrémentale : persiste juste après chaque intent payé."""
    OUT_PATH.write_text(
        json.dumps(list(records_by_id.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def calibrate_one(intent: Intent) -> dict:
    """Exécute light + heavy, génère 1 checklist, note les 2 (appels réseau)."""
    prompt = build_prompt(intent)
    resp_light = call_model(
        config.MODEL_LIGHT, prompt, temperature=0.0,
        max_tokens=config.RESPONSE_MAX_TOKENS,
    )
    resp_heavy = call_model(
        config.MODEL_HEAVY, prompt, temperature=0.0,
        max_tokens=config.RESPONSE_MAX_TOKENS,
    )
    checklist = generate_checklist(intent)
    q_light = judge_rocketeval(intent, resp_light.text, checklist=checklist).q
    q_heavy = judge_rocketeval(intent, resp_heavy.text, checklist=checklist).q
    return {
        "intent_id": intent.id,
        "domain": intent.domain,
        "complexity": intent.expected_complexity,
        "model_light": config.MODEL_LIGHT,
        "model_heavy": config.MODEL_HEAVY,
        "q_light": q_light,
        "q_heavy": q_heavy,
        "latency_light_ms": resp_light.latency_ms,
        "latency_heavy_ms": resp_heavy.latency_ms,
        "cost_light": resp_light.cost_estimate,
        "cost_heavy": resp_heavy.cost_estimate,
        "checklist": list(checklist),
    }


def _select_intents(
    intents: Sequence[Intent],
    sample_size: Optional[int],
    subset: Optional[set[str]],
) -> tuple[Intent, ...]:
    """Restreint l'échantillon : SUBSET (ids ciblés) prime sur SAMPLE_SIZE.

    SAMPLE_SIZE tire un échantillon ÉQUILIBRÉ par complexité (déterministe),
    pour que la matrice qualité×complexité ait des effectifs par classe.
    """
    if subset is not None:
        return tuple(it for it in intents if it.id in subset)
    if sample_size is not None:
        return _balanced_sample(intents, sample_size)
    return tuple(intents)


def _balanced_sample(intents: Sequence[Intent], n: int) -> tuple[Intent, ...]:
    """Balanced draw whose RUN ORDER alternates complexity classes.

    The order matters because the runner pays intents sequentially: a
    class-by-class order (all complex, then medium, then simple) starves the
    last class entirely when the budget dies mid-run. Round-robin interleaving
    keeps every class near-equally covered at any interruption point.
    """
    import random
    from itertools import zip_longest

    rng = random.Random(42)
    by_cx: dict[str, list[Intent]] = {}
    for it in intents:
        by_cx.setdefault(it.expected_complexity, []).append(it)
    per = max(1, n // len(by_cx)) if by_cx else 0
    sampled: list[list[Intent]] = []
    for cx in sorted(by_cx):
        pool = sorted(by_cx[cx], key=lambda x: x.id)
        sampled.append(rng.sample(pool, min(per, len(pool))))
    interleaved = [
        it for round_ in zip_longest(*sampled) for it in round_ if it is not None
    ]
    return tuple(interleaved[:n])


def run(intents: Sequence[Intent]) -> list[dict]:
    """Calibre les intents, reprenable et sauvegardé après chaque appel payé."""
    records_by_id = _load_done()
    if records_by_id:
        print(f"Reprise : {len(records_by_id)} intent(s) déjà calibré(s), ignoré(s).\n")
    for i, intent in enumerate(intents, 1):
        if intent.id in records_by_id:
            continue
        print(f"[{i}/{len(intents)}] {intent.id} : light + heavy + juge ...", flush=True)
        rec = calibrate_one(intent)
        records_by_id[intent.id] = rec
        _save(records_by_id)  # incrémental
        print(
            f"    q_light={rec['q_light']:.2f}  q_heavy={rec['q_heavy']:.2f}  "
            f"(checklist {len(rec['checklist'])} items)",
            flush=True,
        )
    return list(records_by_id.values())


def _print_matrix(summary: dict) -> None:
    print("\n=== Matrice de qualité réelle — q moyen (tier × complexité) ===")
    print(f"  {'complexité':10s} {'n':>3s}  {'light':>6s}  {'heavy':>6s}  {'écart H-L':>9s}")
    for level in _COMPLEXITY_ORDER:
        if level not in summary["matrix"]:
            continue
        m = summary["matrix"][level]
        print(
            f"  {level:10s} {summary['n'][level]:>3d}  "
            f"{m['light']:>6.2f}  {m['heavy']:>6.2f}  {summary['gap'][level]:>+9.2f}"
        )
    o = summary["overall"]
    print(f"  {'overall':10s} {'':>3s}  {o['light']:>6.2f}  {o['heavy']:>6.2f}  {o['gap']:>+9.2f}")
    simple_gap = summary["gap"].get("simple")
    if simple_gap is not None:
        verdict = "le light suffit" if simple_gap < 0.10 else "écart non négligeable"
        print(f"\n  H-B (simple) : écart heavy-light = {simple_gap:+.2f} -> {verdict}.")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    intents = load_intents(config.DATASET_PATH)
    subset_env = os.getenv("SUBSET")
    subset = set(subset_env.split(",")) if subset_env else None
    sample_env = os.getenv("SAMPLE_SIZE")
    sample_size = int(sample_env) if sample_env else None

    selected = _select_intents(intents, sample_size, subset)
    print(f"Calibration sur {len(selected)} intent(s).")
    print(f"Light={config.MODEL_LIGHT}  Heavy={config.MODEL_HEAVY}")
    print(f"Checklist={config.CHECKLIST_MODEL}  Juge={config.JUDGE_MODEL}\n")

    records = run(selected)
    summary = aggregate_quality(records)
    _print_matrix(summary)
    print(f"\nÉcrit : {OUT_PATH}  ({len(records)} intents)")


if __name__ == "__main__":
    main()
