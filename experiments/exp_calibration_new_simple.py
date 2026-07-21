"""Paye heavy + checklist sur des intents SIMPLES neufs (ligne simple propre).

Contexte : la calibration du 2026-07-19/20 n'a que 4 intents simples (les
seuls déjà couverts par les runs stockés), trop peu pour trancher la parité
avec un léger local. Ce script étend la couverture : il ne paie QUE le tier
heavy + la génération de checklist (le tier léger sera rejugé localement,
gratuitement, par exp_calibration_local.py une fois ce fichier produit).

Sélection : intents de complexité "simple" du dataset, EXCLUS ceux déjà
couverts par calibration.json / calibration_llama.json (fonction pure,
testée). Ordre déterministe (tri par id).

Discipline de coût (cf. feedback_openrouter_cost_discipline) : valider sur un
petit N via SAMPLE_SIZE avant le run complet, écriture incrémentale
reprenable.

Usage :
    SAMPLE_SIZE=2 .venv/bin/python -m experiments.exp_calibration_new_simple
    SAMPLE_SIZE=20 .venv/bin/python -m experiments.exp_calibration_new_simple
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from app import config
from app.llm.checklist import generate_checklist
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval
from app.llm.openrouter_client import call_model
from app.llm.schema import Intent
from experiments.exp_calibration import build_prompt
from experiments.exp_calibration_local import STORED_PATHS, merge_stored_records

RESULTS_DIR = Path("experiments/results")
OUT_PATH = RESULTS_DIR / "calibration_new_simple.json"


def select_fresh_simple_intents(
    all_intents: Sequence[Intent], covered_ids: set[str], n: int
) -> tuple[Intent, ...]:
    """Intents "simple" absents des runs déjà stockés (déterministe, triés).

    Args:
        all_intents: dataset complet.
        covered_ids: intent_id déjà couverts par un run heavy+checklist stocké.
        n: nombre d'intents à retenir.

    Returns:
        Jusqu'à n intents de complexité "simple", triés par id, non couverts.
    """
    fresh = sorted(
        (it for it in all_intents if it.expected_complexity == "simple" and it.id not in covered_ids),
        key=lambda it: it.id,
    )
    return tuple(fresh[:n])


def _load_done() -> dict[str, dict]:
    if not OUT_PATH.exists():
        return {}
    return {r["intent_id"]: r for r in json.loads(OUT_PATH.read_text(encoding="utf-8"))}


def _save(records_by_id: dict[str, dict]) -> None:
    OUT_PATH.write_text(
        json.dumps(list(records_by_id.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def pay_one(intent: Intent) -> dict:
    """Paie heavy + checklist pour un intent (appels réseau réels)."""
    resp_heavy = call_model(
        config.MODEL_HEAVY, build_prompt(intent), temperature=0.0,
        max_tokens=config.RESPONSE_MAX_TOKENS,
    )
    checklist = generate_checklist(intent)
    q_heavy = judge_rocketeval(intent, resp_heavy.text, checklist=checklist).q
    return {
        "intent_id": intent.id,
        "domain": intent.domain,
        "complexity": intent.expected_complexity,
        "model_heavy": config.MODEL_HEAVY,
        "q_heavy": q_heavy,
        "latency_heavy_ms": resp_heavy.latency_ms,
        "cost_heavy": resp_heavy.cost_estimate,
        "checklist": list(checklist),
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sample_env = os.getenv("SAMPLE_SIZE")
    n = int(sample_env) if sample_env else 20

    all_intents = load_intents(config.DATASET_PATH)
    covered = merge_stored_records(
        [json.loads(p.read_text(encoding="utf-8")) for p in STORED_PATHS if p.exists()]
    )
    selected = select_fresh_simple_intents(all_intents, set(covered), n)

    done = _load_done()
    if done:
        print(f"Reprise : {len(done)} intent(s) déjà payé(s), ignoré(s).\n")
    print(f"Paiement heavy+checklist sur {len(selected)} intent(s) simple(s) neuf(s).")
    print(f"Heavy={config.MODEL_HEAVY}  Checklist={config.CHECKLIST_MODEL}\n")

    total_cost = sum(r.get("cost_heavy", 0.0) for r in done.values())
    for i, intent in enumerate(selected, 1):
        if intent.id in done:
            continue
        print(f"[{i}/{len(selected)}] {intent.id} ...", flush=True)
        rec = pay_one(intent)
        done[intent.id] = rec
        _save(done)
        total_cost += rec["cost_heavy"]
        print(
            f"    q_heavy={rec['q_heavy']:.2f}  cost=${rec['cost_heavy']:.4f}  "
            f"(cumulé ${total_cost:.4f})",
            flush=True,
        )

    print(f"\nÉcrit : {OUT_PATH}  ({len(done)} intents, coût cumulé ${total_cost:.4f})")


if __name__ == "__main__":
    main()
