from pydantic import BaseModel, Field, field_validator


class InferenceRequest(BaseModel):
    image: str
    scenario: str = Field(default="default")



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


class ThresholdUpdateRequest(BaseModel):
    value: int = Field(..., ge=1, description="New queue threshold value")


class ThresholdUpdateResponse(BaseModel):
    queue_threshold: int
    status: str
