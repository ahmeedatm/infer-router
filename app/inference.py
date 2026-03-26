from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)


async def call_model(model_url: str, image_b64: str, callback_url: str = "") -> dict:
    """POST image to model container. Returns {"accuracy", "latency", "results"}."""
    payload: dict = {"image": image_b64}
    if callback_url:
        payload["callback_url"] = callback_url

    t0 = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(model_url, json=payload)
        resp.raise_for_status()

    body = resp.json()
    return {
        "accuracy": body.get("accuracy"),        # populated via /feedback endpoint
        "latency": round(time.time() - t0, 4),
        "results": body.get("result"),           # model returns key "result", not "results"
    }
