import os

REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
QUEUE_THRESHOLD: int = int(os.getenv("QUEUE_THRESHOLD", 5))
ACCURACY_PENALTY_THRESHOLD: float = float(os.getenv("ACCURACY_PENALTY_THRESHOLD", 0.2))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

FAST_MODEL_NAME: str = "Fast-Model"
ACCURATE_MODEL_NAME: str = "Accurate-Model"

FAST_MODEL_URL: str = os.getenv("FAST_MODEL_URL", "http://model-fast:5002/new_pod_run_model")
ACCURATE_MODEL_URL: str = os.getenv("ACCURATE_MODEL_URL", "http://model-accurate:5002/new_pod_run_model")
CLIENT_CALLBACK_URL: str = os.getenv("CLIENT_CALLBACK_URL", "http://host.docker.internal:5002/save_result")

THRESHOLD_REDIS_KEY: str = "config:queue_threshold"
INFERENCE_QUEUE_KEY: str = "inference_queue"
RESULTS_KEY_PREFIX: str = "inference_results"
ACCURACY_KEY_PREFIX: str = "accuracy"
RESULTS_MAX_LEN: int = 1000
DEFAULT_SCENARIO: str = "default"
