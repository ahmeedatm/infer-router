"""Generate oracle action artifacts (the correct SdnAction per intent) for every
strategy, so the bench pipeline can be validated end-to-end without a live LLM.

This is NOT the real phase-A experiment (which runs the target models per
strategy, cf. experiments/run_realworld_validation.py). It exercises the bench
plumbing: with correct actions, every intent should be realised.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.llm.sdn_action import SdnAction
from bench.subset import load_subset

_RESULTS = Path(__file__).resolve().parent.parent / "experiments" / "results" / "realworld"
_STRATEGIES = ("light", "heavy", "inferrouter")


def _oracle(entry) -> SdnAction:
    gt = entry.ground_truth
    if entry.klass == "reachability":
        return SdnAction(intent_id=entry.intent_id, action="allow", src=gt.src, dst=gt.dst)
    if entry.klass == "isolation":
        return SdnAction(intent_id=entry.intent_id, action="block", src=gt.src, dst=gt.dst)
    return SdnAction(
        intent_id=entry.intent_id, action="bandwidth",
        src=gt.src, dst=gt.dst, bw_mbps=gt.max_mbps,
    )


def main() -> int:
    for entry in load_subset():
        action = _oracle(entry)
        for strategy in _STRATEGIES:
            out = _RESULTS / strategy
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{entry.intent_id}.json").write_text(json.dumps(action.model_dump()))
    print(f"oracle artifacts written under {_RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
