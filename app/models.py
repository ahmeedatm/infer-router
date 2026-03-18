from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InferenceRequest(BaseModel):
    sensor_id: str
    timestamp: float
    features: list[float]
    scenario: str = Field(default="default")


class InferenceResult(BaseModel):
    sensor_id: str
    model: str
    latency: float
    queue_at_start: int
    scenario: str
    processed_at: Optional[float] = None
    accuracy: Optional[float] = None
    routing_reason: Optional[str] = None


KNOWN_MODELS = {"Fast-Model", "Accurate-Model"}


class FeedbackRequest(BaseModel):
    model: str
    accuracy: float

    @field_validator("model")
    @classmethod
    def model_must_be_known(cls, v: str) -> str:
        if v not in KNOWN_MODELS:
            raise ValueError(f"Unknown model '{v}'. Must be one of: {', '.join(sorted(KNOWN_MODELS))}")
        return v

    @field_validator("accuracy")
    @classmethod
    def accuracy_must_be_valid(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("accuracy must be between 0.0 and 1.0")
        return v


class FeedbackResponse(BaseModel):
    model: str
    accuracy: float
    status: str


class ResultsResponse(BaseModel):
    scenario: str
    results: list[dict]


class ScenariosResponse(BaseModel):
    scenarios: list[str]


class QueuedResponse(BaseModel):
    status: str
    scenario: str
