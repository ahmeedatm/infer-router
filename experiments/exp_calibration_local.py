"""Calibration d'un léger LOCAL (Ollama), à coût API nul.

Contexte : les crédits OpenRouter sont épuisés. On réutilise les artefacts
déjà payés (réponse du heavy notée q_heavy + checklist RocketEval par intent,
stockés par les runs précédents) et on ne génère EN LOCAL que la réponse du
nouveau candidat léger (MODEL_LIGHT_LOCAL, défaut qwen2.5:7b-instruct), notée
par le juge local avec la MÊME checklist. Total : 0 $.

Sources fusionnées (voir merge_stored_records, pure et testée) :
- experiments/results/calibration.json        (grand run, 45 intents, 0 simple)
- experiments/results/calibration_llama.json  (run équilibré, 12 intents, 4 simples)

L'ordre d'exécution alterne les complexités (round-robin) : une interruption
laisse chaque classe à couverture proche, là où l'ancien ordre par classe
avait privé la classe simple de toute mesure.

Limite assumée : n(simple)=4 tant qu'aucun crédit API ne permet de payer de
nouvelles réponses heavy sur des intents simples. La latence mesurée est celle
de CETTE machine (indicative, pas benchmark).

Usage :
    JUDGE_MODEL=gemma2:9b .venv/bin/python -m experiments.exp_calibration_local
"""
from __future__ import annotations

import json
import os
from itertools import zip_longest
from pathlib import Path
from typing import Sequence

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval
from app.llm.ollama_client import call_model
from experiments.exp_calibration import build_prompt

RESULTS_DIR = Path("experiments/results")
STORED_PATHS = (
    RESULTS_DIR / "calibration.json",
    RESULTS_DIR / "calibration_llama.json",
)
# Sortie par défaut ; surchargée par run (un fichier PAR modèle léger testé,
# sinon la reprise d'un modèle sauterait les intents déjà traités par l'autre).
OUT_PATH = Path(
    os.getenv("CALIBRATION_LOCAL_OUT", str(RESULTS_DIR / "calibration_local.json"))
)

_COMPLEXITY_ORDER = ("simple", "medium", "complex")


# ── Fonctions pures ─────────────────────────────────────────────────────────


def merge_stored_records(sources: Sequence[list[dict]]) -> dict[str, dict]:
    """Fusionne les runs stockés en un référentiel {intent_id: record}.

    La première source listée prime sur les suivantes pour un même intent_id
    (le grand run est plus récent que le run équilibré). Seuls les champs
    réutilisables sont conservés : complexity, checklist, q_heavy.

    Args:
        sources: listes de records issus des JSON de calibration précédents.

    Returns:
        dict intent_id -> {complexity, checklist, q_heavy}, sans doublon.
    """
    merged: dict[str, dict] = {}
    for records in sources:
        for rec in records:
            iid = rec["intent_id"]
            if iid in merged:
                continue
            merged[iid] = {
                "complexity": rec["complexity"],
                "checklist": list(rec["checklist"]),
                "q_heavy": rec["q_heavy"],
            }
    return merged


def interleave_by_complexity(records: dict[str, dict]) -> list[str]:
    """Ordonne les intent_ids en alternant les complexités (round-robin).

    Déterministe (tri par id dans chaque classe). Une interruption du run
    laisse ainsi chaque classe avec une couverture proche de l'équilibre.
    """
    by_cx: dict[str, list[str]] = {}
    for iid in sorted(records):
        by_cx.setdefault(records[iid]["complexity"], []).append(iid)
    lanes = [by_cx[cx] for cx in _COMPLEXITY_ORDER if cx in by_cx]
    extra = [by_cx[cx] for cx in sorted(by_cx) if cx not in _COMPLEXITY_ORDER]
    return [
        iid
        for round_ in zip_longest(*(lanes + extra))
        for iid in round_
        if iid is not None
    ]


# ── Runner reprenable (génération locale + juge local) ──────────────────────


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
    light = config.MODEL_LIGHT_LOCAL
    stored = _load_sources()
    order = interleave_by_complexity(stored)
    intents = {it.id: it for it in load_intents(config.DATASET_PATH)}

    done: dict[str, dict] = {}
    if OUT_PATH.exists():
        done = {
            r["intent_id"]: r
            for r in json.loads(OUT_PATH.read_text(encoding="utf-8"))
        }
        print(f"Reprise : {len(done)} intent(s) déjà traités, ignorés.\n")

    print(f"Calibration LOCALE : léger={light} (Ollama), juge={config.JUDGE_MODEL}")
    print(f"{len(order)} intents réutilisables (heavy + checklist stockés)\n")

    rows = list(done.values())
    for i, iid in enumerate(order, 1):
        if iid in done:
            continue
        if iid not in intents:
            print(f"[{i}/{len(order)}] {iid} absent du dataset courant, ignoré.")
            continue
        rec = stored[iid]
        resp = call_model(light, build_prompt(intents[iid]), temperature=0.0)
        q = judge_rocketeval(
            intents[iid], resp.text, checklist=tuple(rec["checklist"])
        ).q
        print(
            f"[{i}/{len(order)}] {iid} ({rec['complexity']}): "
            f"q_local={q:.2f} vs q_heavy={rec['q_heavy']:.2f} "
            f"({resp.latency_ms / 1000:.0f}s)",
            flush=True,
        )
        rows.append(
            {
                "intent_id": iid,
                "complexity": rec["complexity"],
                "q_light_local": q,
                "q_heavy": rec["q_heavy"],
                "model_light_local": light,
                "judge_model": config.JUDGE_MODEL,
                "latency_light_local_ms": resp.latency_ms,
                "completion_tokens": resp.completion_tokens,
            }
        )
        OUT_PATH.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    _print_matrix(rows, light)


def _print_matrix(rows: list[dict], light: str) -> None:
    print(f"\n=== Matrice — léger local {light} vs heavy (réutilisé) ===")
    print("  complexité   n   local   heavy   écart H-L")
    for cx in _COMPLEXITY_ORDER:
        sub = [r for r in rows if r["complexity"] == cx]
        if not sub:
            continue
        n = len(sub)
        l = sum(r["q_light_local"] for r in sub) / n
        h = sum(r["q_heavy"] for r in sub) / n
        print(f"  {cx:8s}    {n:2d}   {l:.2f}    {h:.2f}    {h - l:+.2f}")
    if rows:
        l = sum(r["q_light_local"] for r in rows) / len(rows)
        h = sum(r["q_heavy"] for r in rows) / len(rows)
        print(f"  {'overall':8s}   {len(rows):2d}   {l:.2f}    {h:.2f}    {h - l:+.2f}")


if __name__ == "__main__":
    main()
