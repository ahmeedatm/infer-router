"""Discrimination fine PAR PAIRES (correct vs dégradé) avec juge local.

La notation par scores indépendants (judge_rocketeval) sous-discrimine : sur
gemma2:9b elle ne donne que 5 % de préférence correcte et 90 % d'égalités (le
juge met le même score à la bonne réponse et à sa variante dégradée d'une seule
erreur). Hypothèse : montrer les DEUX réponses au juge et lui demander laquelle
est meilleure (judge_pairwise) discrimine mieux, car la comparaison est relative
et non absolue.

Réutilise les paires (degraded_pairs.json) et les checklists déjà générées
(exp_a_responses_rocketeval.json) : AUCUN appel OpenRouter. Reprenable (écriture
incrémentale) et JUDGE_MODEL piloté par env, comme experiments/exp_d_9b.py.

Vérité-terrain : la réponse CORRECTE doit gagner. On passe toujours correct
comme response_a et degraded comme response_b ; le double-appel interne de
judge_pairwise neutralise déjà le biais de position.

Usage :
    JUDGE_MODEL=gemma2:9b .venv/bin/python -m experiments.exp_d_pairwise
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge_pairwise

PAIRS = Path("experiments/results/degraded_pairs.json")
ROCKET = Path("experiments/results/exp_a_responses_rocketeval.json")
OUT = Path("experiments/results/exp_d_pairwise.json")


def main() -> None:
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))
    checklists = {
        r["intent_id"]: tuple(r["checklist"])
        for r in json.loads(ROCKET.read_text(encoding="utf-8"))
    }
    intents = {it.id: it for it in load_intents()}
    print(
        f"Discrimination fine PAR PAIRES avec JUDGE_MODEL = {config.JUDGE_MODEL} "
        f"(checklists réutilisées)\n"
    )

    done = {}
    if OUT.exists():
        done = {r["intent_id"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}

    rows = list(done.values())
    for i, p in enumerate(pairs, 1):
        iid = p["intent_id"]
        if iid in done or iid not in checklists:
            continue
        intent = intents[iid]
        verdict = judge_pairwise(
            intent,
            p["correct_text"],
            p["degraded_text"],
            checklist=checklists[iid],
        )
        # "A" == juge préfère la correcte (passée en response_a).
        print(f"[{i}/{len(pairs)}] {iid} ({p['error_type']}): verdict={verdict}")
        rows.append({"intent_id": iid, "error_type": p["error_type"], "verdict": verdict})
        OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    _report(rows)


def _report(rows: list[dict]) -> None:
    n = len(rows)
    if n == 0:
        print("Aucune paire évaluée (vérifier degraded_pairs / checklists).")
        return
    correct = sum(1 for r in rows if r["verdict"] == "A")
    tie = sum(1 for r in rows if r["verdict"] == "tie")
    inv = sum(1 for r in rows if r["verdict"] == "B")
    print(f"\n=== Discrimination fine PAR PAIRES — juge {config.JUDGE_MODEL} ===")
    print(
        f"  n={n} | préférence correcte={correct / n:.0%} | "
        f"égalités={tie / n:.0%} | inversions={inv / n:.0%}"
    )
    print("  (rappel : scores indépendants 9b = 5% correct / 90% tie / 5% inversion)")
    by: dict[str, list[int]] = {}
    for r in rows:
        bucket = by.setdefault(r["error_type"], [0, 0])
        bucket[1] += 1
        if r["verdict"] == "A":
            bucket[0] += 1
    print("  ventilation par error_type (préférence correcte) :")
    for et, (c, t) in sorted(by.items()):
        print(f"    {et:14s}: {c}/{t} corrects")


if __name__ == "__main__":
    main()
