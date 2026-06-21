"""Expérience A — accord juge ↔ référence (hypothèse H-A) + signal H-B.

`compute_agreement` est pure (pas d'I/O) donc testable. Le bloc __main__ lit
les fichiers produits par exp_a_judge_reliability.py et un CSV de verdicts.

Convention d'accord : la préférence du juge (déduite de q_light/q_heavy et du
mapping A/B) est comparée au verdict de référence (A/B/egal). On compte un
accord lorsque les deux préférences coïncident exactement (A=A, B=B, egal=egal).
Un « egal » d'un seul côté est compté comme désaccord (choix conservateur,
documenté : on ne veut pas gonfler artificiellement l'accord).

Lancer :  .venv/bin/python -m experiments.exp_a_agreement
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

RESULTS_DIR = Path("experiments/results")
RESPONSES_PATH = RESULTS_DIR / "exp_a_responses.json"
VERDICTS_PATH = RESULTS_DIR / "exp_a_verdicts.csv"


def judge_preference(record: dict) -> str:
    """Préférence du juge en termes de labels A/B, à partir des q."""
    q_a = record["q_light"] if record["label_A"] == "light" else record["q_heavy"]
    q_b = record["q_light"] if record["label_B"] == "light" else record["q_heavy"]
    if q_a > q_b:
        return "A"
    if q_b > q_a:
        return "B"
    return "egal"


def reference_prefers_heavy(record: dict, verdict: str) -> str:
    """Traduit le verdict A/B/egal en préférence light/heavy/egal."""
    if verdict == "egal":
        return "egal"
    chosen_label = "label_A" if verdict == "A" else "label_B"
    return record[chosen_label]  # "light" ou "heavy"


def compute_agreement(responses: list[dict], verdicts: dict[str, str]) -> dict:
    """Fonction pure. Retourne accord global, par complexité, et signal H-B."""
    total = 0
    agree = 0
    by_level: dict[str, dict[str, int]] = {}
    hb_pref: dict[str, dict[str, int]] = {}  # complexité -> {light,heavy,egal}

    for rec in responses:
        if rec.get("error"):
            continue
        verdict = verdicts.get(rec["intent_id"])
        if verdict is None:
            continue
        verdict = verdict.strip().lower()
        verdict = {"a": "A", "b": "B", "egal": "egal", "égal": "egal"}.get(verdict, verdict)

        level = rec["expected_complexity"]
        by_level.setdefault(level, {"agree": 0, "total": 0})
        hb_pref.setdefault(level, {"light": 0, "heavy": 0, "egal": 0})

        total += 1
        by_level[level]["total"] += 1
        if judge_preference(rec) == verdict:
            agree += 1
            by_level[level]["agree"] += 1

        hb_pref[level][reference_prefers_heavy(rec, verdict)] += 1

    return {
        "n": total,
        "agreement": (agree / total) if total else 0.0,
        "agree_count": agree,
        "by_complexity": {
            lvl: {**v, "rate": (v["agree"] / v["total"]) if v["total"] else 0.0}
            for lvl, v in by_level.items()
        },
        "reference_preference_by_complexity": hb_pref,
    }


def _load_verdicts(path: Path) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            verdicts[row["intent_id"].strip()] = row["verdict"]
    return verdicts


def main() -> None:
    responses = json.loads(RESPONSES_PATH.read_text(encoding="utf-8"))
    verdicts = _load_verdicts(VERDICTS_PATH)
    result = compute_agreement(responses, verdicts)

    print("=== Expérience A — accord juge ↔ référence (H-A) ===")
    print(f"n = {result['n']}  ·  accord global = {result['agreement']:.0%} ({result['agree_count']}/{result['n']})")
    print("\nPar complexité :")
    for lvl in ("simple", "medium", "complex"):
        v = result["by_complexity"].get(lvl)
        if v:
            print(f"  {lvl:8s}: {v['rate']:.0%} ({v['agree']}/{v['total']})")
    print("\n=== Signal H-B — préférence de référence (light/heavy/egal) ===")
    for lvl in ("simple", "medium", "complex"):
        p = result["reference_preference_by_complexity"].get(lvl)
        if p:
            print(f"  {lvl:8s}: light={p['light']}  heavy={p['heavy']}  egal={p['egal']}")

    verdict = result["agreement"]
    print("\n=== Verdict H-A ===")
    if verdict >= 0.80:
        print(f"  ✅ Accord {verdict:.0%} ≥ 80% : juge fiable, H-A validée.")
    elif verdict >= 0.60:
        print(f"  ⚠ Accord {verdict:.0%} (60-80%) : juge utilisable mais à surveiller.")
    else:
        print(f"  ❌ Accord {verdict:.0%} < 60% : juge peu fiable, H-A en alerte rouge.")


if __name__ == "__main__":
    main()
