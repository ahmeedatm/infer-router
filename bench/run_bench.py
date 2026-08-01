"""Full bench run (inside the Lima VM): replay actions, measure, tabulate.

Reads the phase-A artifacts, drives Mininet + OVS per intent/strategy, applies
each action directly on the switches, verifies the data plane, writes the
realization table. Run as root (Mininet needs it).

``noop`` and ``oracle`` are part of the sweep as controls, not as routing
strategies. ``noop`` applies a plan with no network effect, so every check it
still passes is a check no model can influence; ``oracle`` applies the plan
derived from the intent's ground truth, so every check it still fails is a
check no model can satisfy. Rationale in
``experiments.run_realworld_validation``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.artifacts import assert_artifacts_complete, load_plan
from bench.orchestrator import run_case
from bench.subset import load_subset
from bench.topology import MininetRunner, build_topology
from experiments.aggregate_realization import render_table

_RESULTS = Path("experiments/results/realworld")
_STRATEGIES = ("light", "heavy", "inferrouter", "noop", "oracle")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    # The negative control is meant to run on its own, before any paid
    # campaign: requiring the priced strategies' artifacts to exist would
    # make the cheapest, most informative run the most expensive to reach.
    parser.add_argument("--strategy", choices=(*_STRATEGIES, "all"), default="all")
    args = parser.parse_args(argv)
    strategies = _STRATEGIES if args.strategy == "all" else (args.strategy,)

    entries = load_subset()
    # Tens of minutes of Mininet runs follow and the sweep cannot be resumed,
    # so refuse incomplete inputs now rather than partway through.
    assert_artifacts_complete(entries, strategies, _RESULTS)

    results = []
    for entry in entries:
        for strategy in strategies:
            plan = load_plan(strategy, entry.intent_id, _RESULTS)
            net = build_topology(entry.topology)
            runner = MininetRunner(net)
            try:
                results.append(run_case(entry, plan, strategy, runner))
            finally:
                runner.stop()
    table = render_table(results)
    # A partial sweep must not overwrite the full campaign's tables.
    suffix = "" if args.strategy == "all" else f"-{args.strategy}"
    (_RESULTS / f"realization_table{suffix}.md").write_text(table + "\n")
    (_RESULTS / f"cases{suffix}.json").write_text(
        json.dumps([r.model_dump() for r in results], indent=2)
    )
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
