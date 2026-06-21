"""Discrimination fine (paires correct/dégradé) avec juge local configurable.

Réutilise les paires dégradées (degraded_pairs.json) et les checklists déjà
générées (exp_a_responses_rocketeval.json), donc AUCUN appel OpenRouter. Teste
si un juge local plus gros (gemma2:9b) préfère la bonne réponse à sa variante
dégradée mieux que le 2b (qui plafonnait à 35 %).

Usage :
    JUDGE_MODEL=gemma2:9b .venv/bin/python -m experiments.exp_d_9b
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval

PAIRS = Path("experiments/results/degraded_pairs.json")
ROCKET = Path("experiments/results/exp_a_responses_rocketeval.json")
OUT = Path("experiments/results/exp_d_9b.json")


def main() -> None:
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))
    checklists = {r["intent_id"]: tuple(r["checklist"]) for r in json.loads(ROCKET.read_text(encoding="utf-8"))}
    intents = {it.id: it for it in load_intents()}
    print(f"Discrimination fine avec JUDGE_MODEL = {config.JUDGE_MODEL} (checklists réutilisées)\n")

    done = {}
    if OUT.exists():
        done = {r["intent_id"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}

    rows = list(done.values())
    for i, p in enumerate(pairs, 1):
        iid = p["intent_id"]
        if iid in done or iid not in checklists:
            continue
        intent = intents[iid]
        cl = checklists[iid]
        qc = judge_rocketeval(intent, p["correct_text"], checklist=cl).q
        qd = judge_rocketeval(intent, p["degraded_text"], checklist=cl).q
        print(f"[{i}/{len(pairs)}] {iid} ({p['error_type']}): q_correct={qc:.2f} q_degraded={qd:.2f}")
        rows.append({"intent_id": iid, "error_type": p["error_type"], "q_correct": qc, "q_degraded": qd})
        OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    _report(rows)


def _report(rows) -> None:
    n = len(rows)
    correct = sum(1 for r in rows if r["q_correct"] > r["q_degraded"])
    tie = sum(1 for r in rows if r["q_correct"] == r["q_degraded"])
    inv = sum(1 for r in rows if r["q_correct"] < r["q_degraded"])
    print(f"\n=== Discrimination fine — juge {config.JUDGE_MODEL} ===")
    print(f"  n={n} | préférence correcte={correct/n:.0%} | égalités={tie/n:.0%} | inversions={inv/n:.0%}")
    print("  (rappel : 2b = 35% préférence correcte)")
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(r["error_type"], [0, 0])
        by[r["error_type"]][1] += 1
        if r["q_correct"] > r["q_degraded"]:
            by[r["error_type"]][0] += 1
    for et, (c, t) in by.items():
        print(f"    {et:14s}: {c}/{t} corrects")


if __name__ == "__main__":
    main()
