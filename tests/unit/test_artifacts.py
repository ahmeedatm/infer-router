"""Phase-A artefact loading: a missing file and a recorded failure are not
the same fact, and the bench must not confuse them."""
from __future__ import annotations

import json

import pytest

from app.llm.intent_plan import IntentPlan
from bench.artifacts import BenchStateError, assert_artifacts_complete, load_plan
from bench.subset import EndpointRef, PingFail, SubsetEntry

_PLAN = {
    "intent_id": "e1",
    "operations": [{"verb": "block", "src": "a", "dst": "b"}],
}


def _entry(intent_id: str = "e1") -> SubsetEntry:
    return SubsetEntry(
        intent_id=intent_id, text="block a from b", domain="security",
        criticality="high", expected_complexity="simple", topology="diamond4",
        endpoints={
            "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
            "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
        },
        checks=(PingFail(check="ping_fail", src="a", dst="b"),),
    )


def _write(root, strategy: str, intent_id: str, payload: dict) -> None:
    out = root / strategy
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{intent_id}.json").write_text(json.dumps(payload))


def test_load_plan_returns_the_stored_plan(tmp_path):
    _write(tmp_path, "light", "e1", _PLAN)
    plan = load_plan("light", "e1", tmp_path)
    assert isinstance(plan, IntentPlan)
    assert plan.operations[0].verb == "block"


def test_a_recorded_model_failure_loads_as_none(tmp_path):
    """``None`` is reserved for the failure marker: phase A saw a completion
    and could not use it, which is a measured model failure."""
    _write(tmp_path, "light", "e1", {"failed": True, "reason": "no JSON"})
    assert load_plan("light", "e1", tmp_path) is None


def test_a_missing_artefact_raises_instead_of_returning_none(tmp_path):
    """A missing file means phase A never ran for this pair. Returning None
    would score the model as having produced no valid plan, manufacturing a
    failure out of a bench state error."""
    with pytest.raises(BenchStateError) as excinfo:
        load_plan("light", "e1", tmp_path)
    assert "e1" in str(excinfo.value)


def test_assert_artifacts_complete_passes_when_everything_is_present(tmp_path):
    for strategy in ("light", "heavy"):
        _write(tmp_path, strategy, "e1", _PLAN)
    assert_artifacts_complete((_entry(),), ("light", "heavy"), tmp_path)


def test_assert_artifacts_complete_raises_before_the_run_starts(tmp_path):
    """Cheap up-front failure beats discovering a hole 40 minutes into a run
    that cannot be resumed."""
    _write(tmp_path, "light", "e1", _PLAN)
    with pytest.raises(BenchStateError) as excinfo:
        assert_artifacts_complete((_entry(),), ("light", "heavy"), tmp_path)
    assert "heavy" in str(excinfo.value)


def test_assert_artifacts_complete_reports_every_hole_at_once(tmp_path):
    entries = (_entry("e1"), _entry("e2"))
    with pytest.raises(BenchStateError) as excinfo:
        assert_artifacts_complete(entries, ("light", "heavy"), tmp_path)
    message = str(excinfo.value)
    for token in ("e1", "e2", "light", "heavy"):
        assert token in message


def test_a_failure_marker_counts_as_present(tmp_path):
    """The marker is a real artefact: phase A ran and recorded its outcome."""
    _write(tmp_path, "light", "e1", {"failed": True, "reason": "no JSON"})
    assert_artifacts_complete((_entry(),), ("light",), tmp_path)
