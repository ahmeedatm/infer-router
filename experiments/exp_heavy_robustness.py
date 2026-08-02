"""Robustesse du choix du modèle lourd : claude-sonnet-4.6 est-il remplaçable ?

Contexte : le lourd (claude-sonnet-4.6) n'a jamais été challengé ni justifié
dans le rapport, asymétrie avec le léger qui a eu droit à tout un gradient
d'expérimentation (3B -> 72B). Ce script teste si la parité mesurée
(qwen2.5-72b-instruct vs claude-sonnet-4.6) et le gain de coût qui en découle
tiennent face à un second candidat lourd (ex. claude-opus-4.8).

Réutilise systématiquement ce qui est déjà payé :
- q_light2 (qualité du léger) : repris tel quel de calibration_api_light.json,
  la qualité du léger ne dépend pas du choix du lourd.
- Checklist par intent : reprise TELLE QUELLE (pas régénérée) depuis les
  runs stockés (générée à l'origine par claude-sonnet-4.6), pour que light,
  sonnet et le nouveau candidat soient jugés sur des critères identiques.
Ne paie donc QUE la génération + le jugement du nouveau candidat lourd.

Usage :
    SAMPLE_SIZE=2 HEAVY_CANDIDATE=anthropic/claude-opus-4.8 \
        .venv/bin/python -m experiments.exp_heavy_robustness
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval
from app.llm.openrouter_client import call_model
from experiments.exp_calibration import build_prompt
from experiments.exp_calibration_local import (
    STORED_PATHS,
    interleave_by_complexity,
    merge_stored_records,
)

LIGHT_RESULTS_PATH = Path("experiments/results/calibration_api_light.json")
OUT_PATH = Path("experiments/results/heavy_robustness.json")


def _load_light_reference() -> dict[str, dict]:
    """intent_id -> {complexity, q_light2, q_heavy (claude-sonnet original)}."""
    records = json.loads(LIGHT_RESULTS_PATH.read_text(encoding="utf-8"))
    return {r["intent_id"]: r for r in records}


def _load_checklists() -> dict[str, list[str]]:
    """intent_id -> checklist EXACTE déjà générée par claude-sonnet-4.6.

    Réutilisée telle quelle (pas régénérée) pour que light/sonnet/candidat
    soient jugés sur des critères identiques, condition de comparabilité.
    """
    sources = [
        json.loads(p.read_text(encoding="utf-8")) for p in STORED_PATHS if p.exists()
    ]
    merged = merge_stored_records(sources)
    return {iid: rec["checklist"] for iid, rec in merged.items()}


def main() -> None:
    candidate = os.environ["HEAVY_CANDIDATE"]
    reference = _load_light_reference()
    checklists = _load_checklists()
    order = interleave_by_complexity(
        {iid: {"complexity": r["complexity"]} for iid, r in reference.items()}
    )
    intents = {it.id: it for it in load_intents(config.DATASET_PATH)}

    sample_env = os.getenv("SAMPLE_SIZE")
    if sample_env:
        order = order[: int(sample_env)]

    done: dict[str, dict] = {}
    if OUT_PATH.exists():
        done = {r["intent_id"]: r for r in json.loads(OUT_PATH.read_text(encoding="utf-8"))}
        print(f"Reprise : {len(done)} intent(s) déjà traités, ignorés.\n")

    print(f"Robustesse du lourd : candidat={candidate}  (checklist par {config.CHECKLIST_MODEL})")
    print(f"{len(order)} intents dans cet appel\n")

    rows = list(done.values())
    total_cost = sum(r.get("cost_heavy_candidate", 0.0) for r in done.values())
    for i, iid in enumerate(order, 1):
        if iid in done:
            continue
        intent = intents[iid]
        ref = reference[iid]
        checklist = tuple(checklists[iid])
        resp = call_model(
            candidate, build_prompt(intent), temperature=0.0,
            max_tokens=config.RESPONSE_MAX_TOKENS,
        )
        q_candidate = judge_rocketeval(intent, resp.text, checklist=checklist).q
        total_cost += resp.cost_estimate
        print(
            f"[{i}/{len(order)}] {iid} ({ref['complexity']}): "
            f"q_light={ref['q_light2']:.2f} q_sonnet={ref['q_heavy']:.2f} "
            f"q_{candidate.split('/')[-1]}={q_candidate:.2f} "
            f"(${resp.cost_estimate:.5f}, cumulé ${total_cost:.4f})",
            flush=True,
        )
        rows.append({
            "intent_id": iid,
            "complexity": ref["complexity"],
            "q_light2": ref["q_light2"],
            "q_heavy_sonnet": ref["q_heavy"],
            "q_heavy_candidate": q_candidate,
            "heavy_candidate": candidate,
            "latency_heavy_candidate_ms": resp.latency_ms,
            "cost_heavy_candidate": resp.cost_estimate,
        })
        OUT_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    _print_matrix(rows, candidate)


def _print_matrix(rows: list[dict], candidate: str) -> None:
    label = candidate.split("/")[-1]
    print(f"\n=== Robustesse du lourd — light / sonnet / {label} ===")
    print(f"  complexité   n   light   sonnet   {label}")
    for cx in ("simple", "medium", "complex"):
        sub = [r for r in rows if r["complexity"] == cx]
        if not sub:
            continue
        n = len(sub)
        q_light = sum(r["q_light2"] for r in sub) / n
        s = sum(r["q_heavy_sonnet"] for r in sub) / n
        c = sum(r["q_heavy_candidate"] for r in sub) / n
        print(f"  {cx:8s}    {n:2d}   {q_light:.2f}    {s:.2f}     {c:.2f}")
    if rows:
        n = len(rows)
        q_light = sum(r["q_light2"] for r in rows) / n
        s = sum(r["q_heavy_sonnet"] for r in rows) / n
        c = sum(r["q_heavy_candidate"] for r in rows) / n
        print(f"  {'overall':8s}   {n:2d}   {q_light:.2f}    {s:.2f}     {c:.2f}")


if __name__ == "__main__":
    main()
