"""Expérience D — pouvoir de discrimination du juge par paires contrôlées.

Problème adressé : opposer un modèle fort à un faible donne une référence qui
préfère toujours le fort (pas de variance), ce qui rend la métrique d'accord
dégénérée. Ici on construit des paires (réponse correcte, réponse dégradée) où
la dégradée est la correcte avec UNE erreur injectée précise. La vérité-terrain
est connue : la correcte est toujours meilleure. On mesure à quelle fréquence le
juge la préfère, l'ignore (égalité) ou se trompe (inversion).

`discrimination_score` est pure (pas d'I/O) donc testable. Le bloc `main` lit
`degraded_pairs.json`, génère la checklist par intent et note les deux textes
avec le même juge RocketEval, puis appelle `discrimination_score`. Le `main`
fait des appels réseau réels : il ne doit pas tourner en test.

Lancer :  .venv/bin/python -m experiments.exp_d_discrimination
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.llm.checklist import generate_checklist
from app.llm.intents import load_intents
from app.llm.judge import judge_rocketeval

PAIRS_PATH = Path("experiments/results/degraded_pairs.json")
ERROR_TYPES: tuple[str, ...] = ("wrong_number", "missing_step", "false_claim")


def _empty_bucket() -> dict[str, int]:
    return {"correct_count": 0, "tie_count": 0, "inversion_count": 0}


def _classify(q_correct: float, q_degraded: float) -> str:
    """Classe une paire : préférence correcte, égalité, ou inversion."""
    if q_correct > q_degraded:
        return "correct"
    if q_correct < q_degraded:
        return "inversion"
    return "tie"


def _rates(bucket: dict[str, int]) -> dict:
    """Convertit un compteur en compteurs + taux (immutabilité : nouvelle dict)."""
    n = bucket["correct_count"] + bucket["tie_count"] + bucket["inversion_count"]
    safe = n if n else 1
    return {
        "n": n,
        "correct_count": bucket["correct_count"],
        "tie_count": bucket["tie_count"],
        "inversion_count": bucket["inversion_count"],
        "correct_preference_rate": bucket["correct_count"] / safe if n else 0.0,
        "tie_rate": bucket["tie_count"] / safe if n else 0.0,
        "inversion_rate": bucket["inversion_count"] / safe if n else 0.0,
    }


def discrimination_score(results: list[dict]) -> dict:
    """Fonction pure. Mesure le pouvoir de discrimination du juge.

    Args:
        results: liste de dicts {intent_id, error_type, q_correct, q_degraded}.

    Returns:
        Un dict avec, globalement et par error_type :
        - correct_preference_rate : #(q_correct > q_degraded) / n
        - tie_rate                : #(q_correct == q_degraded) / n
        - inversion_rate          : #(q_correct < q_degraded) / n
    """
    overall = _empty_bucket()
    by_type: dict[str, dict[str, int]] = {}

    for res in results:
        outcome = _classify(res["q_correct"], res["q_degraded"])
        key = f"{outcome}_count"
        overall[key] += 1
        bucket = by_type.setdefault(res["error_type"], _empty_bucket())
        bucket[key] += 1

    summary = _rates(overall)
    summary["by_error_type"] = {etype: _rates(b) for etype, b in by_type.items()}
    return summary


def _load_pairs(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Paires dégradées introuvables : {path}. "
            "Lancer d'abord : .venv/bin/python -m experiments.build_degraded_pairs"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _score_pair(intent, pair: dict) -> dict:
    """Note la paire correcte/dégradée avec la même checklist (appels réseau)."""
    checklist = generate_checklist(intent)
    q_correct = judge_rocketeval(
        intent, pair["correct_text"], checklist=checklist
    ).q
    q_degraded = judge_rocketeval(
        intent, pair["degraded_text"], checklist=checklist
    ).q
    return {
        "intent_id": pair["intent_id"],
        "error_type": pair["error_type"],
        "q_correct": q_correct,
        "q_degraded": q_degraded,
    }


def _print_report(summary: dict) -> None:
    print("=== Expérience D — discrimination du juge (paires contrôlées) ===")
    print(
        f"n = {summary['n']}  ·  "
        f"préférence correcte = {summary['correct_preference_rate']:.0%} "
        f"({summary['correct_count']}/{summary['n']})"
    )
    print(
        f"  égalités  = {summary['tie_rate']:.0%} ({summary['tie_count']})  ·  "
        f"inversions = {summary['inversion_rate']:.0%} ({summary['inversion_count']})"
    )
    print("\nPar type d'erreur injectée :")
    for etype in ERROR_TYPES:
        v = summary["by_error_type"].get(etype)
        if v:
            print(
                f"  {etype:13s}: correct={v['correct_count']}  "
                f"egal={v['tie_count']}  inversion={v['inversion_count']}  "
                f"(pref. correcte {v['correct_preference_rate']:.0%})"
            )

    rate = summary["correct_preference_rate"]
    print("\n=== Verdict — pouvoir de discrimination ===")
    if rate >= 0.80:
        print(f"  OK  préférence correcte {rate:.0%} >= 80% : juge discriminant.")
    elif rate >= 0.60:
        print(f"  ~   préférence correcte {rate:.0%} (60-80%) : discriminant partiel.")
    else:
        print(f"  X   préférence correcte {rate:.0%} < 60% : juge peu discriminant.")


def main() -> None:
    pairs = _load_pairs(PAIRS_PATH)
    intents = {it.id: it for it in load_intents()}

    print(f"Juge RocketEval — checklist générée par {config.CHECKLIST_MODEL}")
    print(f"Grading local par {config.JUDGE_MODEL}\n")

    results: list[dict] = []
    for i, pair in enumerate(pairs, 1):
        intent = intents[pair["intent_id"]]
        print(
            f"[{i}/{len(pairs)}] {pair['intent_id']} "
            f"({pair['error_type']}) : notation ...",
            flush=True,
        )
        result = _score_pair(intent, pair)
        results.append(result)
        print(
            f"    q_correct={result['q_correct']:.2f}  "
            f"q_degraded={result['q_degraded']:.2f}",
            flush=True,
        )

    summary = discrimination_score(results)
    print()
    _print_report(summary)


if __name__ == "__main__":
    main()
