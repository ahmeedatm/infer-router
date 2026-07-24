"""Full bench run (inside the Lima VM): replay actions, measure, tabulate.

Reads the phase-A artifacts, drives Mininet + OVS per intent/strategy, applies
each action directly on the switches, verifies the data plane, writes the
realization table. Run as root (Mininet needs it).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.llm.sdn_action import SdnAction
from bench.orchestrator import run_case
from bench.subset import load_subset
from bench.topology import MininetRunner, build_topology
from experiments.aggregate_realization import realization_rate, render_table

_RESULTS = Path("experiments/results/realworld")
_STRATEGIES = ("light", "heavy", "inferrouter")


def _load_action(strategy: str, intent_id: str) -> SdnAction:
    data = json.loads((_RESULTS / strategy / f"{intent_id}.json").read_text())
    return SdnAction(**data)


def main() -> int:
    results = []
    for entry in load_subset():
        for strategy in _STRATEGIES:
            net = build_topology(entry.topology)
            runner = MininetRunner(net)
            try:
                action = _load_action(strategy, entry.intent_id)
                results.append(run_case(entry, action, strategy, runner))
            finally:
                runner.stop()
    rates = realization_rate(results)
    table = render_table(rates)
    (_RESULTS / "realization_table.md").write_text(table + "\n")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
