"""Calibration d'un léger API-hébergé (MODEL_LIGHT2), qui remplace le léger local.

Contexte : qwen2.5:14b-instruct (validé en local, parité sur simple) n'est pas
hébergé sur OpenRouter, et le poste de développement (MacBook Air) ne peut pas
fournir une mesure de LATENCE représentative. Ce script réutilise les
artefacts déjà payés (heavy + checklist, mêmes 74 intents que
exp_calibration_local.py) et ne paie que la génération d'un candidat léger
HÉBERGÉ (ex. qwen2.5-72b-instruct), noté par le juge local avec la même
checklist. Seul le juge tourne en local : aucune concurrence mémoire avec un
second modèle local, contrairement à exp_calibration_local.py.

Le léger étant servi par l'API, sa latence mesurée ici (resp.latency_ms) est
directement utilisable pour le benchmark final (P50/P99), sans le biais du
matériel de développement ni du rechargement Ollama entre deux modèles.

Usage :
    SAMPLE_SIZE=2 MODEL_LIGHT2=qwen/qwen-2.5-72b-instruct \
        .venv/bin/python -m experiments.exp_calibration_api_light
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

# Sortie paramétrable : un fichier par léger testé, sinon la reprise sauterait
# les intents déjà traités par un autre modèle.
OUT_PATH = Path(
    os.getenv("CALIBRATION_API_OUT", "experiments/results/calibration_api_light.json")
)


def _load_sources() -> dict[str, dict]:
    sources = []
    for path in STORED_PATHS:
        if path.exists():
            sources.append(json.loads(path.read_text(encoding="utf-8")))
        else:
            print(f"AVERTISSEMENT : source absente ignorée : {path}")
    if not sources:
        raise SystemExit("Aucune source de calibration stockée : rien à réutiliser.")
    return merge_stored_records(sources)


def main() -> None:
    light2 = os.environ["MODEL_LIGHT2"]
    stored = _load_sources()
    order = interleave_by_complexity(stored)
    intents = {it.id: it for it in load_intents(config.DATASET_PATH)}

    sample_env = os.getenv("SAMPLE_SIZE")
    if sample_env:
        order = order[: int(sample_env)]

    done: dict[str, dict] = {}
    if OUT_PATH.exists():
        done = {r["intent_id"]: r for r in json.loads(OUT_PATH.read_text(encoding="utf-8"))}
        print(f"Reprise : {len(done)} intent(s) déjà traités, ignorés.\n")

    print(f"Calibration API : léger={light2} (OpenRouter), juge={config.JUDGE_MODEL}")
    print(f"{len(order)} intents dans cet appel\n")

    rows = list(done.values())
    total_cost = sum(r.get("cost_light2", 0.0) for r in done.values())
    for i, iid in enumerate(order, 1):
        if iid in done:
            continue
        if iid not in intents:
            print(f"[{i}/{len(order)}] {iid} absent du dataset courant, ignoré.")
            continue
        rec = stored[iid]
        resp = call_model(
            light2, build_prompt(intents[iid]), temperature=0.0,
            max_tokens=config.RESPONSE_MAX_TOKENS,
            # Novita rejette qwen2.5-72b-instruct sur cet endpoint (HTTP 400
            # "does not support endpoint: completions", 2026-07-21) alors que
            # d'autres fournisseurs le servent sans souci ; on l'exclut.
            provider={"ignore": ["novita"]},
        )
        q = judge_rocketeval(intents[iid], resp.text, checklist=tuple(rec["checklist"])).q
        total_cost += resp.cost_estimate
        print(
            f"[{i}/{len(order)}] {iid} ({rec['complexity']}): "
            f"q_light2={q:.2f} vs q_heavy={rec['q_heavy']:.2f} "
            f"({resp.latency_ms:.0f}ms, ${resp.cost_estimate:.5f}, cumulé ${total_cost:.4f})",
            flush=True,
        )
        rows.append({
            "intent_id": iid,
            "complexity": rec["complexity"],
            "q_light2": q,
            "q_heavy": rec["q_heavy"],
            "model_light2": light2,
            "latency_light2_ms": resp.latency_ms,
            "cost_light2": resp.cost_estimate,
        })
        OUT_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    _print_matrix(rows, light2)


def _print_matrix(rows: list[dict], light2: str) -> None:
    print(f"\n=== Matrice — léger API {light2} vs heavy (réutilisé) ===")
    print("  complexité   n   light2   heavy   écart H-L   latence_p50_ms")
    for cx in ("simple", "medium", "complex"):
        sub = [r for r in rows if r["complexity"] == cx]
        if not sub:
            continue
        n = len(sub)
        l = sum(r["q_light2"] for r in sub) / n
        h = sum(r["q_heavy"] for r in sub) / n
        lat = sorted(r["latency_light2_ms"] for r in sub)[n // 2]
        print(f"  {cx:8s}    {n:2d}   {l:.2f}    {h:.2f}    {h - l:+.2f}       {lat:.0f}")
    if rows:
        n = len(rows)
        l = sum(r["q_light2"] for r in rows) / n
        h = sum(r["q_heavy"] for r in rows) / n
        print(f"  {'overall':8s}   {n:2d}   {l:.2f}    {h:.2f}    {h - l:+.2f}")


if __name__ == "__main__":
    main()
