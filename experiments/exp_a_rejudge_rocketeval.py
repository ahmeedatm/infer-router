"""Re-note les réponses v2 avec le juge RocketEval COMPLET (checklist générée).

Teste si une checklist générée par intent (via le modèle fort) corrige
l'aveuglement à l'hallucination du juge à checklist fixe. La checklist est
générée une fois par intent puis réutilisée pour noter light et heavy.

Variable d'env optionnelle SUBSET : liste d'intent_id séparés par virgule, pour
un test diagnostique à bas coût (ex : les cas d'hallucination) avant le run
complet.

Usage :
    SUBSET=core-read-amf-registrations,slice-read-active-count,ran-read-prb-utilization \
        .venv/bin/python -m experiments.exp_a_rejudge_rocketeval
    .venv/bin/python -m experiments.exp_a_rejudge_rocketeval   # tout
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app import config
from app.llm.checklist import generate_checklist
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval

RESPONSES_PATH = Path("experiments/results/exp_a_responses_v2.json")
OUT_PATH = Path("experiments/results/exp_a_responses_rocketeval.json")


def main() -> None:
    records = json.loads(RESPONSES_PATH.read_text(encoding="utf-8"))
    intents = {it.id: it for it in load_intents()}
    subset = os.getenv("SUBSET")
    wanted = set(subset.split(",")) if subset else None

    print(f"Juge RocketEval complet — checklist générée par {config.CHECKLIST_MODEL}")
    print(f"Grading local par {config.JUDGE_MODEL}\n")

    out = []
    for i, rec in enumerate(records, 1):
        if rec.get("error"):
            continue
        if wanted is not None and rec["intent_id"] not in wanted:
            continue
        intent = intents[rec["intent_id"]]
        print(f"[{i}/{len(records)}] {rec['intent_id']} : génération checklist ...", flush=True)
        checklist = generate_checklist(intent)
        q_light = judge_rocketeval(intent, rec["response_light"], checklist=checklist).q
        q_heavy = judge_rocketeval(intent, rec["response_heavy"], checklist=checklist).q
        new = dict(rec)
        new["q_light"], new["q_heavy"] = q_light, q_heavy
        new["checklist"] = list(checklist)
        out.append(new)
        print(
            f"    checklist={len(checklist)} items | q_light={q_light:.2f}  q_heavy={q_heavy:.2f}",
            flush=True,
        )

    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nÉcrit : {OUT_PATH}  ({len(out)} intents)")


if __name__ == "__main__":
    main()
