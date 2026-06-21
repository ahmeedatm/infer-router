"""Re-jugement local (gratuit) des réponses stockées avec un juge configurable.

Réutilise les réponses ET les checklists RocketEval déjà générées
(experiments/results/exp_a_responses_rocketeval.json), donc AUCUN appel
OpenRouter. Seul le juge local (Ollama, env JUDGE_MODEL) change. But : tester si
un juge local plus gros (gemma2:9b) discrimine mieux que le 2b, sans renier la
contribution « juge local ».

Usage :
    JUDGE_MODEL=gemma2:9b .venv/bin/python -m experiments.exp_judge_9b_rocketeval
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval

SRC = Path("experiments/results/exp_a_responses_rocketeval.json")
VERDICTS = Path("experiments/results/exp_a_verdicts.csv")
OUT = Path("experiments/results/exp_a_rocketeval_9b.json")


def _verdicts() -> dict[str, str]:
    out: dict[str, str] = {}
    with VERDICTS.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["intent_id"].strip()] = row["verdict"].strip()
    return out


def main() -> None:
    recs = json.loads(SRC.read_text(encoding="utf-8"))
    intents = {it.id: it for it in load_intents()}
    verdicts = _verdicts()
    print(f"Re-jugement local avec JUDGE_MODEL = {config.JUDGE_MODEL} (checklists réutilisées)\n")

    done = {}
    if OUT.exists():
        done = {r["intent_id"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}

    rows = list(done.values())
    for i, rec in enumerate(recs, 1):
        iid = rec["intent_id"]
        if iid in done:
            continue
        intent = intents[iid]
        checklist = tuple(rec["checklist"])
        ql = judge_rocketeval(intent, rec["response_light"], checklist=checklist).q
        qh = judge_rocketeval(intent, rec["response_heavy"], checklist=checklist).q
        print(f"[{i}/{len(recs)}] {iid} ({rec['expected_complexity']}): q_light={ql:.2f} q_heavy={qh:.2f}")
        rows.append({"intent_id": iid, "expected_complexity": rec["expected_complexity"],
                     "q_light": ql, "q_heavy": qh,
                     "label_A": rec["label_A"], "label_B": rec["label_B"]})
        OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    _report(rows, verdicts)


def _report(rows, verdicts) -> None:
    agree = 0
    counted = 0
    for r in rows:
        v = verdicts.get(r["intent_id"])
        if not v:
            continue
        counted += 1
        q_a = r["q_light"] if r["label_A"] == "light" else r["q_heavy"]
        q_b = r["q_light"] if r["label_B"] == "light" else r["q_heavy"]
        pref = "A" if q_a > q_b else "B" if q_b > q_a else "egal"
        agree += pref == v
    print(f"\n=== Juge {config.JUDGE_MODEL} + RocketEval — accord vs référence ===")
    print(f"  accord global = {agree}/{counted} = {agree / counted:.0%}" if counted else "  pas de verdicts")
    print("  (rappel : 2b+RocketEval = 90%, 2b checklist fixe = 40%, 9b checklist fixe = 50%)")


if __name__ == "__main__":
    main()
