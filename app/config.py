import os

REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
QUEUE_THRESHOLD: int = int(os.getenv("QUEUE_THRESHOLD", 5))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

FAST_MODEL_NAME: str = "Fast-Model"
ACCURATE_MODEL_NAME: str = "Accurate-Model"
FAST_MODEL_LATENCY: float = 0.5
ACCURATE_MODEL_LATENCY: float = 2.0

INFERENCE_QUEUE_KEY: str = "inference_queue"
RESULTS_KEY_PREFIX: str = "inference_results"
RESULTS_MAX_LEN: int = 1000
DEFAULT_SCENARIO: str = "default"
