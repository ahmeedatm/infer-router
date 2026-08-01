"""Full bench run (inside the Lima VM): replay actions, measure, tabulate.

Reads the phase-A artifacts, drives Mininet + OVS per intent/strategy, applies
each action directly on the switches, verifies the data plane, writes the
realization table. Run as root (Mininet needs it).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.llm.intent_plan import IntentPlan
from bench.orchestrator import run_case
from bench.subset import load_subset
from bench.topology import MininetRunner, build_topology
from experiments.aggregate_realization import render_table

_RESULTS = Path("experiments/results/realworld")
_STRATEGIES = ("light", "heavy", "inferrouter")


def _load_plan(strategy: str, intent_id: str) -> Optional[IntentPlan]:
    """Return the strategy's plan, or None if missing or marked failed."""
    path = _RESULTS / strategy / f"{intent_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("failed"):
        return None
    return IntentPlan(**data)


def main() -> int:
    results = []
    for entry in load_subset():
        for strategy in _STRATEGIES:
            net = build_topology(entry.topology)
            runner = MininetRunner(net)
            try:
                results.append(run_case(
                    entry, _load_plan(strategy, entry.intent_id), strategy, runner
                ))
            finally:
                runner.stop()
    table = render_table(results)
    (_RESULTS / "realization_table.md").write_text(table + "\n")
    (_RESULTS / "cases.json").write_text(
        json.dumps([r.model_dump() for r in results], indent=2)
    )
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
