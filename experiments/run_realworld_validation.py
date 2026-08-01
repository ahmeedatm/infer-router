"""Phase A (Mac): produce each strategy's operation plan for every intent.

Writes one IntentPlan JSON per intent/strategy, consumed inside the VM by
bench.run_bench. A completion that cannot be parsed is written with
``{"failed": true}`` so the bench scores it as a total failure rather than
skipping the case.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from app import config
from app.llm.intent_plan import IntentPlan, IntentPlanError, build_plan_prompt, parse_plan_response
from app.llm.inferrouter import route
from app.llm.openrouter_client import call_model
from app.llm.schema import Intent, ModelResponse
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
            expected_complexity=entry.expected_complexity,
            criticality=entry.criticality,
        )
        decision = route(intent, l_max=1e9, c_max=1e9)
        return decision.model_id or config.MODEL_HEAVY
    raise ValueError(f"unknown strategy {strategy!r}")


def plan_for(
    entry: SubsetEntry,
    strategy: str,
    call: Callable[..., ModelResponse] = call_model,
) -> IntentPlan:
    """Ask the strategy's model for this intent's operation plan."""
    model_id = _model_for(entry, strategy)
    prompt = build_plan_prompt(entry.text, list(entry.endpoints))
    reply = call(model_id, prompt, max_tokens=config.RESPONSE_MAX_TOKENS)
    return parse_plan_response(entry.intent_id, reply.text)


def _write(strategy: str, intent_id: str, payload: dict) -> None:
    out = _RESULTS / strategy
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{intent_id}.json").write_text(json.dumps(payload))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=(*_STRATEGIES, "all"), default="all")
    parser.add_argument("--subset", default=None)
    args = parser.parse_args(argv)
    strategies = _STRATEGIES if args.strategy == "all" else (args.strategy,)
    for entry in load_subset(args.subset):
        for strategy in strategies:
            try:
                plan = plan_for(entry, strategy)
            except IntentPlanError as exc:
                _write(strategy, entry.intent_id,
                       {"failed": True, "reason": str(exc)})
                print(f"{strategy}/{entry.intent_id}: FAILED ({exc})")
                continue
            _write(strategy, entry.intent_id, plan.model_dump())
            verbs = ",".join(op.verb for op in plan.operations)
            print(f"{strategy}/{entry.intent_id}: [{verbs}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
