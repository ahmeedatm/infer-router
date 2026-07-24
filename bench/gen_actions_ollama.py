"""Phase A (local, offline): produce each strategy's structured action with
local Ollama models, so the bench yields a real per-strategy differential
without spending OpenRouter credits.

- light  -> a weak model (gemma2:2b): may emit malformed / wrong actions.
- heavy  -> a strong model (qwen2.5:14b-instruct).
- inferrouter -> reuses the heavy action on complex intents, the light one
  otherwise (the routing decision), so no extra inference call.

A parse failure is recorded as {"intent_id": ..., "failed": true}; run_bench
counts such a case as not realised.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.llm.ollama_client import call_model
from app.llm.sdn_action import (
    SdnActionError,
    build_action_prompt,
    parse_action_response,
)
from bench.subset import SubsetEntry, load_subset

_RESULTS = Path(__file__).resolve().parent.parent / "experiments" / "results" / "realworld"
_LIGHT = "gemma2:2b"
_HEAVY = "qwen2.5:14b-instruct"


def _action_dict(entry: SubsetEntry, model_id: str) -> dict:
    prompt = build_action_prompt(entry.text, list(entry.endpoints))
    reply = call_model(model_id, prompt)
    try:
        return parse_action_response(entry.intent_id, reply.text).model_dump()
    except SdnActionError:
        return {"intent_id": entry.intent_id, "failed": True}


def _is_complex(entry: SubsetEntry) -> bool:
    try:
        from experiments.train_complexity_estimator import predict_complexity
        return predict_complexity([entry.text])[0] == "complex"
    except Exception:
        return False


def _write(strategy: str, intent_id: str, data: dict) -> None:
    out = _RESULTS / strategy
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{intent_id}.json").write_text(json.dumps(data))


def main() -> int:
    for entry in load_subset():
        light = _action_dict(entry, _LIGHT)
        heavy = _action_dict(entry, _HEAVY)
        routed = heavy if _is_complex(entry) else light
        _write("light", entry.intent_id, light)
        _write("heavy", entry.intent_id, heavy)
        _write("inferrouter", entry.intent_id, routed)
        print(f"{entry.intent_id}: light={light.get('action', 'FAILED')} "
              f"heavy={heavy.get('action', 'FAILED')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
