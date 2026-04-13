"""Single source of truth for all Redis key names and prefixes.

Centralised here so every module agrees on naming and future LLM keys
(complexity:..., quality:...) are added in one place.
"""

# ── Queue ──────────────────────────────────────────────────────────────────
INFERENCE_QUEUE_KEY: str = "inference_queue"

# ── Results ────────────────────────────────────────────────────────────────
RESULTS_KEY_PREFIX: str = "inference_results"

# ── Accuracy ───────────────────────────────────────────────────────────────
ACCURACY_KEY_PREFIX: str = "accuracy"

# ── Arrival rate (λ) ───────────────────────────────────────────────────────
ARRIVALS_KEY: str = "metrics:arrivals"
LAMBDA_KEY: str = "metrics:lambda"

# ── Service rate (μ) ───────────────────────────────────────────────────────
LATENCIES_KEY_PREFIX: str = "metrics:latencies"
MU_KEY_PREFIX: str = "metrics:mu"

# ── Threshold FSM ──────────────────────────────────────────────────────────
K_ACTIVE_KEY: str = "metrics:k_active"

# ── AAP sliding window ─────────────────────────────────────────────────────
AAP_WINDOW_KEY_PREFIX: str = "aap:window"

# ── Ephemeral: push latency relay (key = f"{PUSH_LATENCY_KEY_PREFIX}:{sensor_id}") ──
PUSH_LATENCY_KEY_PREFIX: str = "push_latency"
