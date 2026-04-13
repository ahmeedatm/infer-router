# app/request_builder.py
"""Build the enriched inference payload from an incoming InferenceRequest.

Separates payload construction from HTTP routing so main.py stays focused
on request/response wiring, and future LLM extensions can add their own
enrichment (e.g. prompt complexity score) without touching main.py.
"""
from __future__ import annotations

import base64
import time
import uuid

from app.models import InferenceRequest


def build_enriched_payload(request: InferenceRequest) -> dict:
    """Return a JSON-serialisable dict ready to push onto the queue.

    Adds:
      - sensor_id: unique request identifier (UUID4)
      - timestamp: epoch seconds at the moment the request is received
      - image_size: decoded byte length of the image
    """
    image_bytes = base64.b64decode(request.image + "==")
    return {
        **request.model_dump(),
        "sensor_id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "image_size": len(image_bytes),
    }
