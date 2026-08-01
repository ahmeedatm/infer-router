"""Phase A (Mac): produce each strategy's operation plan for every intent.

Writes one IntentPlan JSON per intent/strategy, consumed inside the VM by
bench.run_bench. A completion that cannot be parsed is written with
``{"failed": true}`` so the bench scores it as a total failure rather than
skipping the case.

The ``noop`` strategy is a negative control, not a routing strategy. It calls
no model and emits a plan that is valid, translatable and inert: a single
selector-less ``allow`` between two of the intent's own endpoints, which
``bench.verbs.allow_block`` maps to zero OVS commands. Running the bench
against it leaves the data plane exactly as ``build_topology`` left it, so
every check that still passes under ``noop`` is a check no model can
influence, whatever plan it produced. That is the measurement this control
exists to produce: it separates checks that discriminate from checks that
only look like they do.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from app import config
from app.llm.intent_plan import (
    AllowOp,
    IntentPlan,
    IntentPlanError,
    build_plan_prompt,
    parse_plan_response,
)
from app.llm.inferrouter import route
from app.llm.openrouter_client import call_model
from app.llm.schema import Intent, ModelResponse
from bench.subset import SubsetEntry, load_subset

_RESULTS = Path(__file__).with_name("results") / "realworld"

#: The negative control (see module docstring). Never resolves to a model.
NOOP_STRATEGY = "noop"

_STRATEGIES = ("light", "heavy", "inferrouter", NOOP_STRATEGY)


def noop_plan(entry: SubsetEntry) -> IntentPlan:
    """The control's inert plan: valid, translatable, zero commands."""
    keys = list(entry.endpoints)
    src = keys[0]
    dst = keys[1] if len(keys) > 1 else keys[0]
    return IntentPlan(
        intent_id=entry.intent_id,
        operations=(AllowOp(verb="allow", src=src, dst=dst),),
    )


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
    """Ask the strategy's model for this intent's operation plan.

    ``noop`` short-circuits here, before anything can reach the API: the
    control must be impossible to run up a bill with.
    """
    if strategy == NOOP_STRATEGY:
        return noop_plan(entry)
    model_id = _model_for(entry, strategy)
    prompt = build_plan_prompt(entry.text, list(entry.endpoints))
    reply = call(model_id, prompt, max_tokens=config.RESPONSE_MAX_TOKENS)
    return parse_plan_response(entry.intent_id, reply.text)


def _write(results_dir: Path, strategy: str, intent_id: str, payload: dict) -> None:
    out = results_dir / strategy
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{intent_id}.json").write_text(json.dumps(payload))


def main(
    argv=None,
    *,
    call: Callable[..., ModelResponse] = call_model,
    results_dir: Path = _RESULTS,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=(*_STRATEGIES, "all"), default="all")
    parser.add_argument("--subset", default=None)
    args = parser.parse_args(argv)
    strategies = _STRATEGIES if args.strategy == "all" else (args.strategy,)
    for entry in load_subset(args.subset):
        for strategy in strategies:
            try:
                plan = plan_for(entry, strategy, call)
            except IntentPlanError as exc:
                _write(results_dir, strategy, entry.intent_id,
                       {"failed": True, "reason": str(exc)})
                print(f"{strategy}/{entry.intent_id}: FAILED ({exc})")
                continue
            _write(results_dir, strategy, entry.intent_id, plan.model_dump())
            verbs = ",".join(op.verb for op in plan.operations)
            print(f"{strategy}/{entry.intent_id}: [{verbs}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
