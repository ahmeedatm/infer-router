"""Measure contribution C2: does a domain specialist beat the generic heavy tier?

Until now C2 was assumed rather than measured. The pool carried four
"specialists" (``<heavy>#ran`` and friends) whose quality came from two
hardcoded constants in ``app.config`` (0.92 on-domain, 0.88 off-domain), and
no specialist ever existed technically: ``base_model_id`` stripped the suffix
before the call and every tier received the same framing. This experiment
builds the missing piece (``build_specialist_prompt``) and measures it.

Both arms answer the same intents, are graded by the same local judge against
the same RocketEval checklist, so the only variable is the framing. Results go
to ``experiments/results/specialist_<domain>.json``.

Cost: one checklist (API) plus two heavy answers (API) per intent; grading is
local and free. Resumable — an intent already present in the results file is
skipped, so an interrupted run costs nothing to restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import mean
from typing import Sequence

import yaml

from app import config
from app.llm.checklist import generate_checklist
from app.llm.judge import judge_rocketeval
from app.llm.openrouter_client import call_model
from app.llm.prompting import build_prompt, build_specialist_prompt
from app.llm.schema import Intent

_RESULTS = Path(__file__).with_name("results")
# Novita serves some pool models but rejects this request shape (HTTP 400);
# routing is per-request, so a run without the exclusion fails at random.
_PROVIDERS = {"ignore": ["novita"]}


def load_domain_intents(domain: str, limit: int) -> tuple[Intent, ...]:
    """Intents of one domain, in dataset order, capped at ``limit``."""
    raw = yaml.safe_load(Path(config.DATASET_PATH).read_text())["intents"]
    picked = [Intent(**item) for item in raw if item["domain"] == domain]
    return tuple(picked[:limit])


def _answer(intent: Intent, specialist: bool) -> str:
    prompt = build_specialist_prompt(intent) if specialist else build_prompt(intent)
    reply = call_model(
        config.MODEL_HEAVY, prompt,
        max_tokens=config.RESPONSE_MAX_TOKENS, provider=_PROVIDERS,
    )
    return reply.text


def score_intent(intent: Intent) -> dict:
    """Grade both arms of one intent against a single shared checklist."""
    checklist = generate_checklist(intent)
    generic = _answer(intent, specialist=False)
    specialist = _answer(intent, specialist=True)
    return {
        "intent_id": intent.id,
        "domain": intent.domain,
        "expected_complexity": intent.expected_complexity,
        "n_criteria": len(checklist),
        "q_generic": judge_rocketeval(intent, generic, checklist=checklist).q,
        "q_specialist": judge_rocketeval(intent, specialist, checklist=checklist).q,
    }


def summarize(records: Sequence[dict]) -> dict:
    """Mean quality per arm, plus the paired win/loss/tie counts."""
    gen = [r["q_generic"] for r in records]
    spe = [r["q_specialist"] for r in records]
    return {
        "n": len(records),
        "q_generic": round(mean(gen), 4) if gen else 0.0,
        "q_specialist": round(mean(spe), 4) if spe else 0.0,
        "delta": round(mean(spe) - mean(gen), 4) if gen else 0.0,
        "specialist_wins": sum(1 for r in records if r["q_specialist"] > r["q_generic"]),
        "specialist_loses": sum(1 for r in records if r["q_specialist"] < r["q_generic"]),
        "ties": sum(1 for r in records if r["q_specialist"] == r["q_generic"]),
    }


def main() -> int:
    domain = os.getenv("DOMAIN", "ran")
    limit = int(os.getenv("N_INTENTS", "12"))
    path = _RESULTS / f"specialist_{domain}.json"
    _RESULTS.mkdir(parents=True, exist_ok=True)

    done = {}
    if path.exists():
        done = {r["intent_id"]: r for r in json.loads(path.read_text())["records"]}

    records = list(done.values())
    for intent in load_domain_intents(domain, limit):
        if intent.id in done:
            continue
        record = score_intent(intent)
        records.append(record)
        # Persist after every intent: the API calls are paid, so an
        # interruption must never cost them twice.
        path.write_text(json.dumps(
            {"domain": domain, "summary": summarize(records), "records": records},
            indent=2, ensure_ascii=False,
        ))
        print(f"{record['intent_id']}: générique {record['q_generic']:.2f} "
              f"vs spécialiste {record['q_specialist']:.2f}")

    summary = summarize(records)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
