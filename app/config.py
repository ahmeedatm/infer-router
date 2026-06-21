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


# ════════════════════════════════════════════════════════════════════════════
# Post-pivot — InferRouter-LLM spike (ADR-005)
# Routage d'intents réseau (texte). Découplé de l'app pré-pivot ci-dessus.
# ════════════════════════════════════════════════════════════════════════════

# OpenRouter — LLM cibles
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Couple de modèles cibles du spike (ajustables — cf. Exp. B du plan)
MODEL_LIGHT: str = os.getenv("MODEL_LIGHT", "meta-llama/llama-3.2-3b-instruct")
MODEL_HEAVY: str = os.getenv("MODEL_HEAVY", "anthropic/claude-sonnet-4.6")
OPENROUTER_TIMEOUT_S: float = float(os.getenv("OPENROUTER_TIMEOUT_S", "60.0"))
# Budget de génération (cap de tokens de complétion) des LLM cibles du spike.
# Cap généreux : borne le coût sans tronquer (le modèle lourd monte à ~2700
# tokens sur les intents complexes). NB : les réponses courtes du modèle léger
# ne sont PAS des troncatures de cap mais un arrêt spontané du petit modèle.
RESPONSE_MAX_TOKENS: int = int(os.getenv("RESPONSE_MAX_TOKENS", "4096"))

# Grille tarifaire OpenRouter (USD par 1000 tokens), par model_id.
# Source : page tarifs OpenRouter. À ajuster si le couple de modèles change.
# cost_estimate s'appuie sur cette grille ; tout modèle absent → coût 0.0
# (choix documenté : on préfère 0.0 explicite à une estimation fausse).
MODEL_PRICING_USD_PER_1K: dict[str, dict[str, float]] = {
    "meta-llama/llama-3.2-3b-instruct": {"prompt": 0.000051, "completion": 0.000335},
    "anthropic/claude-sonnet-4.6": {"prompt": 0.003, "completion": 0.015},
}

# LLM-Juge local (Ollama)
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
JUDGE_MODEL: str = os.getenv("JUDGE_MODEL", "gemma2:2b")
# Modèle fort qui génère la checklist RocketEval spécifique à chaque intent
# (via OpenRouter). Réutilise le heavy par défaut.
CHECKLIST_MODEL: str = os.getenv("CHECKLIST_MODEL", MODEL_HEAVY)
# Borne de génération (tokens) pour la production de la checklist.
CHECKLIST_MAX_TOKENS: int = int(os.getenv("CHECKLIST_MAX_TOKENS", "512"))

# Jeu d'intents du spike
INTENTS_SPIKE_PATH: str = os.getenv("INTENTS_SPIKE_PATH", "data/intents_spike.yaml")
