"""Re-calibration du SEUL modèle léger, en réutilisant heavy + checklists.

Discipline de coût (règle 6) : le run llama a déjà produit q_heavy et la
checklist par intent (dans calibration.json). On ne repaie donc ni le heavy ni
la génération de checklist. On génère uniquement la réponse d'un NOUVEAU modèle
léger (env MODEL_LIGHT2) et on la juge avec la checklist stockée, pour voir si
un léger plus fort devient compétitif sur les intents simples.

Usage :
    MODEL_LIGHT2=openai/gpt-4o-mini .venv/bin/python -m experiments.exp_calibration_light2
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

CALIB_PATH = Path("experiments/results/calibration.json")
OUT_PATH = Path("experiments/results/calibration_light2.json")


def main() -> None:
    light2 = os.environ["MODEL_LIGHT2"]
    base = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
    by_id = {r["intent_id"]: r for r in base}
    intents = {it.id: it for it in load_intents(config.DATASET_PATH)}

    done = {}
    if OUT_PATH.exists():
        done = {r["intent_id"]: r for r in json.loads(OUT_PATH.read_text(encoding="utf-8"))}

    print(f"Re-calibration léger = {light2} (heavy + checklists réutilisés)\n")
    rows = list(done.values())
    for i, (iid, rec) in enumerate(by_id.items(), 1):
        if iid in done:
            continue
        intent = intents[iid]
        checklist = tuple(rec["checklist"])
        resp = call_model(light2, build_prompt(intent), temperature=0.0,
                          max_tokens=config.RESPONSE_MAX_TOKENS)
        q = judge_rocketeval(intent, resp.text, checklist=checklist).q
        print(f"[{i}/{len(by_id)}] {iid} ({rec['complexity']}): q_light2={q:.2f}  vs q_heavy={rec['q_heavy']:.2f}")
        rows.append({"intent_id": iid, "complexity": rec["complexity"],
                     "q_light2": q, "q_heavy": rec["q_heavy"], "model_light2": light2})
        OUT_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    _matrix(rows, light2)


def _matrix(rows, light2) -> None:
    print(f"\n=== Matrice — léger {light2} vs heavy (réutilisé) ===")
    print("  complexité   n   light2   heavy   écart H-L2")
    for cx in ("simple", "medium", "complex"):
        sub = [r for r in rows if r["complexity"] == cx]
        if not sub:
            continue
        n = len(sub)
        l2 = sum(r["q_light2"] for r in sub) / n
        h = sum(r["q_heavy"] for r in sub) / n
        print(f"  {cx:8s}    {n}   {l2:.2f}    {h:.2f}     {h - l2:+.2f}")


if __name__ == "__main__":
    main()
