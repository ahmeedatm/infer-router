import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis

from app.config import (
    ACCURATE_MODEL_LATENCY,
    ACCURATE_MODEL_NAME,
    ACCURACY_KEY_PREFIX,
    ACCURACY_PENALTY_THRESHOLD,
    DEFAULT_SCENARIO,
    FAST_MODEL_LATENCY,
    FAST_MODEL_NAME,
    INFERENCE_QUEUE_KEY,
    LOG_LEVEL,
    QUEUE_THRESHOLD,
    REDIS_HOST,
    REDIS_PORT,
    RESULTS_KEY_PREFIX,
)
from app.dashboard import build_dashboard_html
from app.models import (
    FeedbackRequest,
    FeedbackResponse,
    InferenceRequest,
    QueuedResponse,
    ResultsResponse,
    ScenariosResponse,
)
from app.worker import process_inference

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis(host=REDIS_HOST, port=REDIS_PORT)
    worker_task = asyncio.create_task(process_inference(app.state.redis))
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await app.state.redis.aclose()


app = FastAPI(
    title="Infer Router API",
    description="Adaptive inference routing with scenario support",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"message": "Welcome to Infer Router API"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/data", response_model=QueuedResponse)
async def receive_data(data: InferenceRequest):
    await app.state.redis.lpush(INFERENCE_QUEUE_KEY, data.model_dump_json())
    logger.info("Queued %s [scenario=%s]", data.sensor_id, data.scenario)
    return QueuedResponse(status="queued", scenario=data.scenario)


@app.get("/results", response_model=ResultsResponse)
async def get_results(scenario: str = Query(default=DEFAULT_SCENARIO)):
    key = f"{RESULTS_KEY_PREFIX}:{scenario}"
    raw = await app.state.redis.lrange(key, 0, 9)
    results = [json.loads(r) for r in raw]
    return ResultsResponse(scenario=scenario, results=results)


@app.get("/scenarios", response_model=ScenariosResponse)
async def get_scenarios():
    keys = await app.state.redis.keys(f"{RESULTS_KEY_PREFIX}:*")
    prefix = f"{RESULTS_KEY_PREFIX}:"
    names = sorted(
        (k.decode() if isinstance(k, bytes) else k)[len(prefix):]
        for k in keys
    )
    return ScenariosResponse(scenarios=names)


@app.get("/config")
async def get_config():
    return {
        "queue_threshold": QUEUE_THRESHOLD,
        "accuracy_penalty_threshold": ACCURACY_PENALTY_THRESHOLD,
        "fast_model": {"name": FAST_MODEL_NAME, "latency_s": FAST_MODEL_LATENCY},
        "accurate_model": {"name": ACCURATE_MODEL_NAME, "latency_s": ACCURATE_MODEL_LATENCY},
    }


@app.post("/feedback", response_model=FeedbackResponse)
async def post_feedback(feedback: FeedbackRequest):
    await app.state.redis.set(f"{ACCURACY_KEY_PREFIX}:{feedback.model}", str(feedback.accuracy))
    logger.info("Feedback received: model=%s accuracy=%.4f", feedback.model, feedback.accuracy)
    return FeedbackResponse(model=feedback.model, accuracy=feedback.accuracy, status="updated")


@app.get("/accuracy")
async def get_accuracy():
    fast_raw = await app.state.redis.get(f"{ACCURACY_KEY_PREFIX}:{FAST_MODEL_NAME}")
    accurate_raw = await app.state.redis.get(f"{ACCURACY_KEY_PREFIX}:{ACCURATE_MODEL_NAME}")
    return {
        FAST_MODEL_NAME: float(fast_raw) if fast_raw is not None else None,
        ACCURATE_MODEL_NAME: float(accurate_raw) if accurate_raw is not None else None,
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html = await build_dashboard_html(app.state.redis)
    return HTMLResponse(content=html)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
