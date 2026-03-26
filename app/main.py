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

from app.arrival import get_lambda, lambda_updater, record_arrival
from app.config import (
    AAP_WINDOW,
    ACCURATE_MODEL_NAME,
    ACCURATE_MODEL_URL,
    ACCURACY_KEY_PREFIX,
    C_COEFFICIENT,
    DEFAULT_SCENARIO,
    FAST_MODEL_NAME,
    FAST_MODEL_URL,
    INFERENCE_QUEUE_KEY,
    LOG_LEVEL,
    OMEGA,
    REDIS_HOST,
    REDIS_PORT,
    RESULTS_KEY_PREFIX,
    ROUTING_STRATEGY,
    TAU,
)
from app.dashboard import build_dashboard_html
from app.gpp import compute_priority
from app.models import (
    InferenceRequest,
    QueuedResponse,
    ResultsResponse,
    ScenariosResponse,
)
from app.mu import get_mu
from app.threshold import get_k_active
from app.worker import process_inference

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis(host=REDIS_HOST, port=REDIS_PORT)
    worker_task = asyncio.create_task(process_inference(app.state.redis))
    lambda_task = asyncio.create_task(lambda_updater(app.state.redis))
    yield
    worker_task.cancel()
    lambda_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    try:
        await lambda_task
    except asyncio.CancelledError:
        pass
    await app.state.redis.aclose()


app = FastAPI(
    title="Infer Router API",
    description="Adaptive inference routing with scenario support",
    version="4.0.0",
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
    await record_arrival(app.state.redis)
    logger.info(
        "Queued sensor_id=%s [scenario=%s] image_size=%d",
        enriched["sensor_id"], data.scenario, enriched["image_size"],
    )
    return QueuedResponse(status="queued", scenario=data.scenario)


@app.get("/results", response_model=ResultsResponse)
async def get_results(scenario: str = Query(default=DEFAULT_SCENARIO)):
    key = f"{RESULTS_KEY_PREFIX}:{scenario}"
    raw = await app.state.redis.lrange(key, 0, 9)
    results = [json.loads(r) for r in raw]
    return ResultsResponse(scenario=scenario, results=results)


@app.get("/export")
async def export_results(scenario: str = Query(default=DEFAULT_SCENARIO)):
    """Return all stored results for a scenario (no cap). Used for benchmarking."""
    key = f"{RESULTS_KEY_PREFIX}:{scenario}"
    raw = await app.state.redis.lrange(key, 0, -1)
    results = [json.loads(r) for r in raw]
    return {"scenario": scenario, "count": len(results), "results": results}


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
    k_active = await get_k_active(app.state.redis)
    lambda_current = await get_lambda(app.state.redis)
    mu_fast = await get_mu(app.state.redis, FAST_MODEL_NAME)
    mu_accurate = await get_mu(app.state.redis, ACCURATE_MODEL_NAME)
    return {
        "routing_strategy": ROUTING_STRATEGY,
        "tau": TAU,
        "c": C_COEFFICIENT,
        "omega": OMEGA,
        "aap_window": AAP_WINDOW,
        "k_active": k_active,
        "lambda_current": lambda_current,
        "mu": {FAST_MODEL_NAME: mu_fast, ACCURATE_MODEL_NAME: mu_accurate},
        "fast_model": {"name": FAST_MODEL_NAME, "url": FAST_MODEL_URL},
        "accurate_model": {"name": ACCURATE_MODEL_NAME, "url": ACCURATE_MODEL_URL},
    }


@app.get("/accuracy")
async def get_accuracy():
    fast_raw = await app.state.redis.get(f"{ACCURACY_KEY_PREFIX}:{FAST_MODEL_NAME}")
    accurate_raw = await app.state.redis.get(f"{ACCURACY_KEY_PREFIX}:{ACCURATE_MODEL_NAME}")
    mu_fast = await get_mu(app.state.redis, FAST_MODEL_NAME)
    mu_accurate = await get_mu(app.state.redis, ACCURATE_MODEL_NAME)

    fast_acc = float(fast_raw) if fast_raw is not None else None
    accurate_acc = float(accurate_raw) if accurate_raw is not None else 1.0

    fast_alpha = max(0.0, 1.0 - fast_acc) if fast_acc is not None else None
    accurate_alpha = 0.0  # gold standard by convention

    return {
        FAST_MODEL_NAME: {
            "accuracy": fast_acc,
            "alpha": fast_alpha,
            "mu": mu_fast,
            "priority": (
                compute_priority(fast_alpha, mu_fast, C_COEFFICIENT, OMEGA)
                if fast_alpha is not None else None
            ),
        },
        ACCURATE_MODEL_NAME: {
            "accuracy": accurate_acc,
            "alpha": accurate_alpha,
            "mu": mu_accurate,
            "priority": compute_priority(accurate_alpha, mu_accurate, C_COEFFICIENT, OMEGA),
        },
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html = await build_dashboard_html(app.state.redis)
    return HTMLResponse(content=html)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
