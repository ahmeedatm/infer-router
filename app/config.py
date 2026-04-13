import os

REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
ROUTING_STRATEGY: str = os.getenv("ROUTING_STRATEGY", "infer-router")
# Valid values: "infer-router" | "always-fast" | "always-accurate"

# Phase 7 — Queue backend
QUEUE_BACKEND: str = os.getenv("QUEUE_BACKEND", "redis")
# Valid values: "redis" | "rabbitmq"
RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

# Phase 4 — InferRouter algorithm parameters
TAU: float = float(os.getenv("TAU", 5.0))           # SLA waiting-time budget (seconds)
C_COEFFICIENT: float = float(os.getenv("C_COEFFICIENT", 1.0))  # GPP cost coefficient
OMEGA: float = float(os.getenv("OMEGA", 1.0))        # GPP calibration weight
AAP_WINDOW: int = int(os.getenv("AAP_WINDOW", 10))   # AAP sliding window size

FAST_MODEL_NAME: str = "Fast-Model"
ACCURATE_MODEL_NAME: str = "Accurate-Model"

FAST_MODEL_URL: str = os.getenv("FAST_MODEL_URL", "http://model-fast:5002/new_pod_run_model")
ACCURATE_MODEL_URL: str = os.getenv("ACCURATE_MODEL_URL", "http://model-accurate:5002/new_pod_run_model")
CLIENT_CALLBACK_URL: str = os.getenv("CLIENT_CALLBACK_URL", "")
# Note: host.docker.internal works on macOS Docker Desktop only.
# On Linux, set CLIENT_CALLBACK_URL to the host LAN IP or use host-gateway.
# Leave empty to disable the callback.

RESULTS_MAX_LEN: int = 1000
DEFAULT_SCENARIO: str = "default"

# ── Algorithmic parameters (overridable for testing / tuning) ──────────────
MU_WINDOW: int = int(os.getenv("MU_WINDOW", "50"))        # latency samples per model for μ computation
LAMBDA_WINDOW_S: float = float(os.getenv("LAMBDA_WINDOW_S", "5.0"))  # arrival-rate sliding window (seconds)
K_MIN: int = 1                                             # fixed lower bound — always keep ≥1 model active
K_MAX: int = int(os.getenv("K_MAX", "2"))                  # max active models in Threshold FSM
