"""Full bench run (inside the Lima VM): replay actions, measure, tabulate.

Reads the phase-A artifacts, drives Mininet + OVS per intent/strategy, applies
each action directly on the switches, verifies the data plane, writes the
realization table. Run as root (Mininet needs it).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.llm.sdn_action import SdnAction
from bench.orchestrator import CaseResult, run_case
from bench.subset import load_subset
from bench.topology import MininetRunner, build_topology
from experiments.aggregate_realization import realization_rate, render_table

_RESULTS = Path("experiments/results/realworld")
_STRATEGIES = ("light", "heavy", "inferrouter")


def _load_action(strategy: str, intent_id: str) -> Optional[SdnAction]:
    """Return the strategy's action, or None if missing / a failed extraction."""
    path = _RESULTS / strategy / f"{intent_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("failed"):
        return None
    return SdnAction(**data)


def main() -> int:
    results = []
    for entry in load_subset():
        for strategy in _STRATEGIES:
            action = _load_action(strategy, entry.intent_id)
            if action is None:
                results.append(CaseResult(
                    intent_id=entry.intent_id, strategy=strategy,
                    satisfied=False, detail="LLM produced no valid action",
                ))
                continue
            net = build_topology(entry.topology)
            runner = MininetRunner(net)
            try:
                results.append(run_case(entry, action, strategy, runner))
            except Exception as exc:
                # A malformed / unrealisable action (bad endpoint, etc.) counts
                # as not realised for that strategy, never a crash of the run.
                results.append(CaseResult(
                    intent_id=entry.intent_id, strategy=strategy,
                    satisfied=False, detail=f"error: {type(exc).__name__}: {exc}",
                ))
            finally:
                runner.stop()
    rates = realization_rate(results)
    table = render_table(rates)
    (_RESULTS / "realization_table.md").write_text(table + "\n")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
