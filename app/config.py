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
CLIENT_CALLBACK_URL: str = os.getenv("CLIENT_CALLBACK_URL", "http://host.docker.internal:5002/save_result")

RESULTS_MAX_LEN: int = 1000
DEFAULT_SCENARIO: str = "default"

# ── Algorithmic parameters (overridable for testing / tuning) ──────────────
MU_WINDOW: int = int(os.getenv("MU_WINDOW", "50"))
# Number of latency samples kept per model for μ computation

LAMBDA_WINDOW_S: float = float(os.getenv("LAMBDA_WINDOW_S", "5.0"))
# Sliding window width (seconds) for arrival rate λ estimation

K_MIN: int = 1
K_MAX: int = int(os.getenv("K_MAX", "2"))
# Min/max number of active models in the Threshold FSM
