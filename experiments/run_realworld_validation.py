"""Phase A (Mac): produce the target LLM's structured action per strategy.

Offline-friendly: never requires a live OpenRouter key when --offline replays
frozen completions. Writes one SdnAction JSON per intent/strategy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from app import config
from app.llm.openrouter_client import call_model
from app.llm.schema import Intent, ModelResponse
from app.llm.sdn_action import SdnAction, build_action_prompt, parse_action_response
from app.llm.inferrouter import route
from bench.subset import SubsetEntry, load_subset

_RESULTS = Path(__file__).with_name("results") / "realworld"
_STRATEGIES = ("light", "heavy", "inferrouter")


def _model_for(entry: SubsetEntry, strategy: str) -> str:
    if strategy == "light":
        return config.MODEL_LIGHT
    if strategy == "heavy":
        return config.MODEL_HEAVY
    if strategy == "inferrouter":
        intent = Intent(
            id=entry.intent_id, text=entry.text, domain=entry.domain,
            expected_complexity="medium", criticality=entry.criticality,
        )
        decision = route(intent, l_max=1e9, c_max=1e9)
        return decision.model_id or config.MODEL_HEAVY
    raise ValueError(f"unknown strategy {strategy!r}")


def action_for(
    entry: SubsetEntry,
    strategy: str,
    call: Callable[..., ModelResponse] = call_model,
) -> SdnAction:
    model_id = _model_for(entry, strategy)
    prompt = build_action_prompt(entry.text, list(entry.endpoints))
    reply = call(model_id, prompt, max_tokens=config.RESPONSE_MAX_TOKENS)
    return parse_action_response(entry.intent_id, reply.text)


def _write(strategy: str, action: SdnAction) -> None:
    out = _RESULTS / strategy
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{action.intent_id}.json").write_text(json.dumps(action.model_dump()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=(*_STRATEGIES, "all"), default="all")
    parser.add_argument("--subset", default=None)
    args = parser.parse_args(argv)
    strategies = _STRATEGIES if args.strategy == "all" else (args.strategy,)
    for entry in load_subset(args.subset):
        for strategy in strategies:
            action = action_for(entry, strategy)
            _write(strategy, action)
            print(f"{strategy}/{entry.intent_id}: {action.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
