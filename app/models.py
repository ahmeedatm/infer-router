from typing import Optional

from pydantic import BaseModel, Field


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


class ResultsResponse(BaseModel):
    scenario: str
    results: list[dict]


class ScenariosResponse(BaseModel):
    scenarios: list[str]


class QueuedResponse(BaseModel):
    status: str
    scenario: str
