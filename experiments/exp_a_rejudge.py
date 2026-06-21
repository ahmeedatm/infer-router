"""Re-note les réponses stockées de l'expérience A avec le juge courant.

Isole la variable « juge » : mêmes 40 réponses, mêmes verdicts de référence,
seul JUDGE_MODEL change. Permet de comparer gemma2:2b vs gemma2:9b (ou autre)
sur l'accord avec la référence, sans rappeler OpenRouter.

Usage :
    JUDGE_MODEL=gemma2:9b .venv/bin/python -m experiments.exp_a_rejudge
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge
from experiments.exp_a_agreement import compute_agreement, VERDICTS_PATH, _load_verdicts

RESPONSES_PATH = Path("experiments/results/exp_a_responses.json")


def main() -> None:
    records = json.loads(RESPONSES_PATH.read_text(encoding="utf-8"))
    intents = {it.id: it for it in load_intents()}
    model = config.JUDGE_MODEL
    print(f"Re-notation avec JUDGE_MODEL = {model}\n")

    rejudged = []
    for i, rec in enumerate(records, 1):
        if rec.get("error"):
            rejudged.append(rec)
            continue
        intent = intents[rec["intent_id"]]
        print(f"[{i}/{len(records)}] {rec['intent_id']} ...", flush=True)
        new = dict(rec)
        new["q_light"] = judge(intent, rec["response_light"]).q
        new["q_heavy"] = judge(intent, rec["response_heavy"]).q
        rejudged.append(new)

    out_path = Path(f"experiments/results/exp_a_responses_{model.replace(':', '_')}.json")
    out_path.write_text(json.dumps(rejudged, indent=2, ensure_ascii=False), encoding="utf-8")

    verdicts = _load_verdicts(VERDICTS_PATH)
    result = compute_agreement(rejudged, verdicts)

    print(f"\n=== Accord juge {model} ↔ référence (H-A) ===")
    print(f"n = {result['n']}  ·  accord global = {result['agreement']:.0%} ({result['agree_count']}/{result['n']})")
    for lvl in ("simple", "medium", "complex"):
        v = result["by_complexity"].get(lvl)
        if v:
            print(f"  {lvl:8s}: {v['rate']:.0%} ({v['agree']}/{v['total']})")
    print(f"\nÉcrit : {out_path}")


if __name__ == "__main__":
    main()
