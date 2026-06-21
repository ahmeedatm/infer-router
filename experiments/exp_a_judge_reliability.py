"""Expérience A du spike — fiabilité du LLM-Juge (hypothèse H-A).

Pour chaque intent du jeu : interroge le modèle light et le modèle heavy via
OpenRouter, fait noter chaque réponse par le LLM-Juge local (gemma2:2b), puis
écrit deux fichiers dans experiments/results/ :

  - exp_a_responses.json : donnée complète (réponses, scores juge, mapping A/B)
  - exp_a_grading.md     : fichier de notation EN AVEUGLE (réponses A/B mélangées,
                           sans score ni nom de modèle)

Le run n'affiche jamais les scores du juge pour ne pas biaiser la notation de
référence. Lancer depuis la racine du repo :

    .venv/bin/python -m experiments.exp_a_judge_reliability
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from app import config
from app.llm.intents import load_intents
from app.llm.judge import judge, JudgeError
from app.llm.openrouter_client import call_model, OpenRouterError
from app.llm.schema import Intent

RESULTS_DIR = Path("experiments/results")
# v2 : régénération avec max_tokens fixé (réponses non tronquées). On n'écrase
# pas les fichiers v1 du premier run (responses/grading/verdicts déjà notés).
RESPONSES_PATH = RESULTS_DIR / "exp_a_responses_v2.json"
GRADING_PATH = RESULTS_DIR / "exp_a_grading_v2.md"
SEED = 42

SYSTEM_PREFIX = (
    "You are a network operations assistant for a 5G/O-RAN operator. "
    "Answer the following operator intent precisely and concisely.\n\nIntent: "
)


def build_prompt(intent: Intent) -> str:
    return f"{SYSTEM_PREFIX}{intent.text}"


def process_intent(intent: Intent, rng: random.Random) -> dict:
    """Interroge light + heavy, note les deux réponses, mélange A/B."""
    prompt = build_prompt(intent)
    record: dict = {
        "intent_id": intent.id,
        "domain": intent.domain,
        "expected_complexity": intent.expected_complexity,
        "model_light": config.MODEL_LIGHT,
        "model_heavy": config.MODEL_HEAVY,
        "error": None,
    }
    try:
        resp_light = call_model(
            config.MODEL_LIGHT,
            prompt,
            temperature=0.0,
            max_tokens=config.RESPONSE_MAX_TOKENS,
        )
        resp_heavy = call_model(
            config.MODEL_HEAVY,
            prompt,
            temperature=0.0,
            max_tokens=config.RESPONSE_MAX_TOKENS,
        )
        score_light = judge(intent, resp_light.text)
        score_heavy = judge(intent, resp_heavy.text)
    except (OpenRouterError, JudgeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    record.update(
        {
            "response_light": resp_light.text,
            "response_heavy": resp_heavy.text,
            "q_light": score_light.q,
            "q_heavy": score_heavy.q,
            "latency_light_ms": resp_light.latency_ms,
            "latency_heavy_ms": resp_heavy.latency_ms,
            "cost_light": resp_light.cost_estimate,
            "cost_heavy": resp_heavy.cost_estimate,
        }
    )
    # Mélange A/B reproductible, indépendant par intent.
    if rng.random() < 0.5:
        record["label_A"], record["label_B"] = "light", "heavy"
    else:
        record["label_A"], record["label_B"] = "heavy", "light"
    return record


def text_for_label(record: dict, label: str) -> str:
    return record["response_light"] if label == "light" else record["response_heavy"]


def write_grading_file(records: list[dict]) -> None:
    lines = [
        "# Expérience A — notation en aveugle",
        "",
        "Pour chaque intent, lis l'énoncé puis les deux réponses. Indique laquelle",
        "traite le mieux l'intent (correction technique, complétude, pertinence).",
        "Reporte ton verdict dans `exp_a_verdicts.csv` : `intent_id,verdict` avec",
        "verdict ∈ {A, B, egal}. Les réponses A/B sont mélangées et anonymisées.",
        "",
        "---",
        "",
    ]
    for rec in records:
        if rec["error"]:
            lines.append(f"## {rec['intent_id']} — ERREUR ({rec['error']}), à ignorer\n")
            continue
        lines.append(f"## {rec['intent_id']}  ·  domaine: {rec['domain']}  ·  complexité: {rec['expected_complexity']}")
        lines.append("")
        lines.append(f"**Intent.** {_intent_text(rec)}")
        lines.append("")
        lines.append("**Réponse A :**")
        lines.append(text_for_label(rec, rec["label_A"]).strip())
        lines.append("")
        lines.append("**Réponse B :**")
        lines.append(text_for_label(rec, rec["label_B"]).strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    GRADING_PATH.write_text("\n".join(lines), encoding="utf-8")


_INTENTS_BY_ID: dict[str, Intent] = {}


def _intent_text(rec: dict) -> str:
    return _INTENTS_BY_ID[rec["intent_id"]].text


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    intents = load_intents()
    _INTENTS_BY_ID.update({it.id: it for it in intents})
    rng = random.Random(SEED)

    records: list[dict] = []
    for i, intent in enumerate(intents, 1):
        print(f"[{i}/{len(intents)}] {intent.id} ...", flush=True)
        rec = process_intent(intent, rng)
        if rec["error"]:
            print(f"    ⚠ {rec['error']}", flush=True)
        records.append(rec)

    RESPONSES_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    write_grading_file(records)

    _print_complexity_recap(records)
    print(f"\nÉcrit : {RESPONSES_PATH}")
    print(f"Écrit : {GRADING_PATH}")


def _print_complexity_recap(records: list[dict]) -> None:
    print("\n=== q moyen par complexité (light / heavy) ===")
    by_level: dict[str, list[tuple[float, float]]] = {}
    for rec in records:
        if rec["error"]:
            continue
        by_level.setdefault(rec["expected_complexity"], []).append((rec["q_light"], rec["q_heavy"]))
    for level in ("simple", "medium", "complex"):
        pairs = by_level.get(level, [])
        if not pairs:
            continue
        n = len(pairs)
        avg_l = sum(p[0] for p in pairs) / n
        avg_h = sum(p[1] for p in pairs) / n
        print(f"  {level:8s} (n={n}): light={avg_l:.2f}  heavy={avg_h:.2f}  écart={avg_h - avg_l:+.2f}")


if __name__ == "__main__":
    main()
