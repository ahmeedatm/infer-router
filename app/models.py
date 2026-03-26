from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    image: str
    scenario: str = Field(default="default")


class ResultsResponse(BaseModel):
    scenario: str
    results: list[dict]


class ScenariosResponse(BaseModel):
    scenarios: list[str]


class QueuedResponse(BaseModel):
    status: str
    scenario: str
