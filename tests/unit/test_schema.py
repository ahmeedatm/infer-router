"""Unit tests for app.llm.schema (pydantic v2 models)."""
import pytest
from pydantic import ValidationError

from app.llm.schema import Intent, JudgeScore, ModelResponse


class TestIntent:
    def _valid_kwargs(self) -> dict:
        return {
            "id": "ran-check-cell",
            "text": "Show the current load on cell 42.",
            "domain": "ran",
            "expected_complexity": "simple",
            "criticality": "low",
        }

    def test_valid_intent(self):
        intent = Intent(**self._valid_kwargs())
        assert intent.id == "ran-check-cell"
        assert intent.slice_type is None

    def test_slice_type_optional_value(self):
        intent = Intent(**{**self._valid_kwargs(), "slice_type": "urllc"})
        assert intent.slice_type == "urllc"

    def test_unknown_domain_rejected(self):
        with pytest.raises(ValidationError):
            Intent(**{**self._valid_kwargs(), "domain": "transport"})

    def test_unknown_complexity_rejected(self):
        with pytest.raises(ValidationError):
            Intent(**{**self._valid_kwargs(), "expected_complexity": "trivial"})

    def test_unknown_criticality_rejected(self):
        with pytest.raises(ValidationError):
            Intent(**{**self._valid_kwargs(), "criticality": "critical"})

    def test_unknown_slice_type_rejected(self):
        with pytest.raises(ValidationError):
            Intent(**{**self._valid_kwargs(), "slice_type": "iot"})

    def test_is_frozen(self):
        intent = Intent(**self._valid_kwargs())
        with pytest.raises(ValidationError):
            intent.id = "mutated"


class TestModelResponse:
    def _valid_kwargs(self) -> dict:
        return {
            "model_id": "meta-llama/llama-3.2-3b-instruct",
            "text": "The cell load is 73%.",
            "latency_ms": 412.5,
            "prompt_tokens": 18,
            "completion_tokens": 9,
            "cost_estimate": 0.0001,
        }

    def test_valid_response(self):
        resp = ModelResponse(**self._valid_kwargs())
        assert resp.completion_tokens == 9

    def test_negative_latency_rejected(self):
        with pytest.raises(ValidationError):
            ModelResponse(**{**self._valid_kwargs(), "latency_ms": -1.0})

    def test_zero_latency_allowed(self):
        resp = ModelResponse(**{**self._valid_kwargs(), "latency_ms": 0.0})
        assert resp.latency_ms == 0.0

    def test_is_frozen(self):
        resp = ModelResponse(**self._valid_kwargs())
        with pytest.raises(ValidationError):
            resp.text = "mutated"


class TestJudgeScore:
    def test_valid_score(self):
        score = JudgeScore(q=0.75, checklist={"correct": True, "complete": False})
        assert score.q == 0.75
        assert score.checklist["correct"] is True

    def test_q_above_one_rejected(self):
        with pytest.raises(ValidationError):
            JudgeScore(q=1.5, checklist={})

    def test_q_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            JudgeScore(q=-0.1, checklist={})

    def test_q_bounds_allowed(self):
        assert JudgeScore(q=0.0, checklist={}).q == 0.0
        assert JudgeScore(q=1.0, checklist={}).q == 1.0

    def test_is_frozen(self):
        score = JudgeScore(q=0.5, checklist={})
        with pytest.raises(ValidationError):
            score.q = 0.9
