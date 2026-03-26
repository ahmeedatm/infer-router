import asyncio
import base64
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis

from app.config import (
    ACCURATE_MODEL_NAME,
    ACCURATE_MODEL_URL,
    ACCURACY_KEY_PREFIX,
    ACCURACY_PENALTY_THRESHOLD,
    DEFAULT_SCENARIO,
    FAST_MODEL_NAME,
    FAST_MODEL_URL,
    INFERENCE_QUEUE_KEY,
    LOG_LEVEL,
    QUEUE_THRESHOLD,
    REDIS_HOST,
    REDIS_PORT,
    RESULTS_KEY_PREFIX,
    THRESHOLD_REDIS_KEY,
)
from app.dashboard import build_dashboard_html
from app.models import (
    FeedbackRequest,
    FeedbackResponse,
    InferenceRequest,
    QueuedResponse,
    ResultsResponse,
    ScenariosResponse,
    ThresholdUpdateRequest,
    ThresholdUpdateResponse,
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
    version="3.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"message": "Welcome to Infer Router API"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/new_pod_run_model", response_model=QueuedResponse)
async def receive_data(data: InferenceRequest):
    image_bytes = base64.b64decode(data.image + "==")
    enriched = {
        **data.model_dump(),
        "sensor_id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "image_size": len(image_bytes),
    }
    await app.state.redis.lpush(INFERENCE_QUEUE_KEY, json.dumps(enriched))
    logger.info("Queued sensor_id=%s [scenario=%s] image_size=%d", enriched["sensor_id"], data.scenario, enriched["image_size"])
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
    raw = await app.state.redis.get(THRESHOLD_REDIS_KEY)
    current_threshold = int(raw) if raw is not None else QUEUE_THRESHOLD
    return {
        "queue_threshold": current_threshold,
        "accuracy_penalty_threshold": ACCURACY_PENALTY_THRESHOLD,
        "fast_model": {"name": FAST_MODEL_NAME, "url": FAST_MODEL_URL},
        "accurate_model": {"name": ACCURATE_MODEL_NAME, "url": ACCURATE_MODEL_URL},
    }


@app.put("/threshold", response_model=ThresholdUpdateResponse)
async def set_threshold(body: ThresholdUpdateRequest):
    await app.state.redis.set(THRESHOLD_REDIS_KEY, str(body.value))
    logger.info("Queue threshold updated to %d", body.value)
    return ThresholdUpdateResponse(queue_threshold=body.value, status="updated")


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
