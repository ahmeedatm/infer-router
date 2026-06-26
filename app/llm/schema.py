"""Immutable pydantic v2 models for InferRouter-LLM.

These schemas describe the data crossing the pipeline:
network intents, raw LLM responses, and judge scores. All models are
frozen (immutable by default, per project coding-style rules).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Domain = Literal["ran", "core", "security", "slice"]
Complexity = Literal["simple", "medium", "complex"]
Criticality = Literal["low", "med", "high"]
SliceType = Literal["embb", "urllc", "mmtc"]


class Intent(BaseModel):
    """A hand-written network intent used to exercise the router."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    domain: Domain
    expected_complexity: Complexity
    criticality: Criticality
    slice_type: Optional[SliceType] = None


class ModelResponse(BaseModel):
    """Result of a single LLM call, with measured latency and usage."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    text: str
    latency_ms: float = Field(ge=0.0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_estimate: float = Field(ge=0.0)


class JudgeScore(BaseModel):
    """Quality score produced by the local LLM-Judge."""

    model_config = ConfigDict(frozen=True)

    q: float = Field(ge=0.0, le=1.0)
    checklist: dict[str, bool]
