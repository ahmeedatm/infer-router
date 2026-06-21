"""Génère des variantes dégradées de réponses de référence (expérience D).

Pour chaque intent, prend `response_heavy` (réponse forte de référence) comme
réponse correcte, puis demande au modèle fort de la réécrire en y injectant UNE
seule erreur ciblée. Trois types d'erreur sont répartis en rotation sur les
intents :
- wrong_number : altère une valeur chiffrée clé,
- missing_step : retire une étape critique en gardant la structure,
- false_claim  : ajoute une affirmation technique fausse mais plausible.

La vérité-terrain est connue par construction : la correcte est toujours
meilleure que la dégradée. Le harnais `exp_d_discrimination` mesure ensuite à
quelle fréquence le juge le retrouve.

Ce script fait des appels réseau réels (OpenRouter via call_model). Tout le code
réseau est dans des fonctions ; seul `if __name__ == '__main__'` les déclenche.

Lancer :  .venv/bin/python -m experiments.build_degraded_pairs
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.llm.openrouter_client import call_model

RESPONSES_PATH = Path("experiments/results/exp_a_responses_v2.json")
OUT_PATH = Path("experiments/results/degraded_pairs.json")

ERROR_TYPES: tuple[str, ...] = ("wrong_number", "missing_step", "false_claim")

# Instruction précise par type d'erreur : une seule erreur, plausible, sans
# changer la longueur, le style ni le formatage de façon visible.
ERROR_INSTRUCTIONS: dict[str, str] = {
    "wrong_number": (
        "Change exactly ONE key numeric value (a threshold, count, percentage, "
        "identifier, or measurement) to a different but plausible number. Change "
        "nothing else."
    ),
    "missing_step": (
        "Remove exactly ONE critical step or instruction, keeping the overall "
        "structure, headings, and length roughly intact so the omission is not "
        "obvious. Change nothing else."
    ),
    "false_claim": (
        "Add exactly ONE technical claim that is factually wrong but plausible "
        "for this network domain, woven naturally into the existing text. Change "
        "nothing else."
    ),
}

DEGRADE_PROMPT_TEMPLATE = (
    "You are preparing a test fixture for evaluating a quality judge. Below is a "
    "correct answer produced by a network-operations assistant. Rewrite it so it "
    "contains EXACTLY ONE injected error, while keeping the length, the writing "
    "style, and the formatting (markdown, headings, lists) visually unchanged. "
    "The error must be precise and plausible enough that a careless reader would "
    "miss it.\n\n"
    "Injected error instruction: {instruction}\n\n"
    "Output ONLY the rewritten answer text. No preamble, no explanation, no note "
    "about what you changed.\n\n"
    "Correct answer:\n{correct_text}\n\n"
    "Rewritten answer with one injected error:"
)


def _error_type_for(index: int) -> str:
    """Rotation des trois types d'erreur sur les intents (par position)."""
    return ERROR_TYPES[index % len(ERROR_TYPES)]


def _build_prompt(correct_text: str, error_type: str) -> str:
    return DEGRADE_PROMPT_TEMPLATE.format(
        instruction=ERROR_INSTRUCTIONS[error_type],
        correct_text=correct_text,
    )


def _degrade_one(correct_text: str, error_type: str) -> str:
    """Appel réseau : produit la variante dégradée via le modèle fort."""
    response = call_model(
        config.CHECKLIST_MODEL,
        _build_prompt(correct_text, error_type),
        temperature=0.0,
        max_tokens=config.RESPONSE_MAX_TOKENS,
    )
    return response.text


def _load_records(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Réponses de référence introuvables : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_done() -> dict[str, dict]:
    """Paires déjà générées (reprise après interruption), indexées par intent."""
    if not OUT_PATH.exists():
        return {}
    existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {p["intent_id"]: p for p in existing}


def _save(pairs_by_id: dict[str, dict]) -> None:
    """Écriture incrémentale : un crash ne perd plus le travail déjà payé."""
    OUT_PATH.write_text(
        json.dumps(list(pairs_by_id.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def build_pairs(records: list[dict]) -> list[dict]:
    """Construit les paires dégradées, reprenable et sauvegardée à chaque pas.

    Saute les intents déjà présents dans degraded_pairs.json. Le type d'erreur
    est dérivé de la position parmi les intents valides, donc stable à la reprise.
    """
    pairs_by_id = _load_done()
    if pairs_by_id:
        print(f"Reprise : {len(pairs_by_id)} paire(s) déjà générée(s), ignorées.\n")
    valid_index = 0
    for rec in records:
        if rec.get("error"):
            continue
        error_type = _error_type_for(valid_index)
        valid_index += 1
        if rec["intent_id"] in pairs_by_id:
            continue
        print(
            f"[{valid_index}] {rec['intent_id']} ({error_type}) : "
            f"génération variante ...",
            flush=True,
        )
        pairs_by_id[rec["intent_id"]] = {
            "intent_id": rec["intent_id"],
            "error_type": error_type,
            "correct_text": rec["response_heavy"],
            "degraded_text": _degrade_one(rec["response_heavy"], error_type),
        }
        _save(pairs_by_id)  # incrémental : persiste juste après l'appel payant
    return list(pairs_by_id.values())


def main() -> None:
    records = _load_records(RESPONSES_PATH)
    print(f"Génération des variantes dégradées via {config.CHECKLIST_MODEL}\n")
    pairs = build_pairs(records)
    print(f"\nÉcrit : {OUT_PATH}  ({len(pairs)} paires)")


if __name__ == "__main__":
    main()
