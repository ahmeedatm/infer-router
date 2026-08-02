"""Loading the phase-A plans the bench replays, and checking they are all there.

Two conditions look alike on disk and mean opposite things:

- ``{"failed": true}`` is a measured model failure. Phase A got a completion
  and could not turn it into a plan, so the case is legitimately scored zero.
- a missing file means phase A never ran for that pair. Scoring it zero
  invents a model failure out of a bench state error.

``load_plan`` returns ``None`` only for the first, and raises for the second.

Kept out of ``bench.run_bench`` (which imports Mininet) so this distinction is
unit-testable on the Mac.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional, Sequence

from app.llm.intent_plan import IntentPlan


class BenchStateError(RuntimeError):
    """Raised when the artefacts a bench run needs are not on disk."""


def plan_path(results_dir: Path, strategy: str, intent_id: str) -> Path:
    return Path(results_dir) / strategy / f"{intent_id}.json"


def load_plan(strategy: str, intent_id: str, results_dir: Path) -> Optional[IntentPlan]:
    """Return the stored plan, or ``None`` if phase A recorded a failure."""
    path = plan_path(results_dir, strategy, intent_id)
    if not path.exists():
        raise BenchStateError(
            f"missing phase-A artefact for {strategy}/{intent_id}: {path}"
        )
    data = json.loads(path.read_text())
    if data.get("failed"):
        return None
    return IntentPlan(**data)


def assert_artifacts_complete(
    entries: Iterable,
    strategies: Sequence[str],
    results_dir: Path,
) -> None:
    """Fail before the run rather than partway through it.

    A bench run takes tens of minutes and cannot be resumed, so every
    (strategy, intent) artefact is checked up front and every hole is
    reported at once.
    """
    missing = [
        str(plan_path(results_dir, strategy, entry.intent_id))
        for entry in entries
        for strategy in strategies
        if not plan_path(results_dir, strategy, entry.intent_id).exists()
    ]
    if missing:
        listing = "\n  ".join(missing)
        raise BenchStateError(
            f"{len(missing)} phase-A artefact(s) missing; run "
            f"experiments/run_realworld_validation.py first:\n  {listing}"
        )
