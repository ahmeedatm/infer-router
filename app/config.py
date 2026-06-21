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
# Retry sur erreurs transitoires (timeout réseau, 429, 5xx, corps non-JSON).
# Un hoquet de passerelle a tué un run complet de génération du dataset ;
# on retente UNIQUEMENT le transitoire (jamais les 4xx définitifs).
# max_retries = nombre de tentatives supplémentaires après le 1er essai.
# Backoff exponentiel : 2s, 4s, 8s... (backoff * 2**attempt).
OPENROUTER_MAX_RETRIES: int = int(os.getenv("OPENROUTER_MAX_RETRIES", "3"))
OPENROUTER_RETRY_BACKOFF_S: float = float(os.getenv("OPENROUTER_RETRY_BACKOFF_S", "2.0"))

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

# Estimateur de complexité sémantique (Exp. H-C) — modèle d'embeddings.
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Génération du dataset d'intents (Plan 3 / ADR-007).
# Modèle fort par défaut : la génération exige du réalisme et de la diversité.
GENERATION_MODEL: str = os.getenv("GENERATION_MODEL", MODEL_HEAVY)
# Dataset cible produit par scripts/generate_dataset.py (même format que le spike).
DATASET_PATH: str = os.getenv("DATASET_PATH", "data/intents_dataset.yaml")

# ────────────────────────────────────────────────────────────────────────────
# Phase 3 — Routeur tri-critère (décision pure, sans réseau)
# ────────────────────────────────────────────────────────────────────────────

# Profils coût/latence par tier du pool prototype. Valeurs relatives
# (le couple light/heavy par défaut). Le coût reprend l'ordre de grandeur de
# la grille tarifaire ci-dessus (USD par appel typique) ; la latence est en ms.
# À recalibrer sur mesures réelles (Phase 5). Surchargeable par env pour les tests.
POOL_LIGHT_COST: float = float(os.getenv("POOL_LIGHT_COST", "0.0004"))
POOL_LIGHT_LATENCY_MS: float = float(os.getenv("POOL_LIGHT_LATENCY_MS", "300.0"))
POOL_HEAVY_COST: float = float(os.getenv("POOL_HEAVY_COST", "0.018"))
POOL_HEAVY_LATENCY_MS: float = float(os.getenv("POOL_HEAVY_LATENCY_MS", "1200.0"))

# Domaines réseau spécialisés du pool (un modèle spécialisé par domaine).
POOL_DOMAINS: tuple[str, ...] = ("ran", "core", "security", "slice")

# Barème de qualité attendue (heuristique de prototype, app/llm/policy.py).
# Toutes les valeurs sont dans [0, 1]. À calibrer par le LLM-Juge en Phase 5.
# Spécialiste sur le domaine de l'intent : forte qualité quelle que soit la complexité.
QUALITY_SPECIALIST_ON_DOMAIN: float = float(os.getenv("QUALITY_SPECIALIST_ON_DOMAIN", "0.92"))
# Heavy générique : bonne qualité générale, stable sur toutes les complexités.
QUALITY_HEAVY_GENERIC: float = float(os.getenv("QUALITY_HEAVY_GENERIC", "0.80"))
# Light générique : base correcte sur intent simple…
QUALITY_LIGHT_BASE: float = float(os.getenv("QUALITY_LIGHT_BASE", "0.70"))
# …mais pénalité croissante avec la complexité (soustraite par cran au-dessus de simple).
QUALITY_LIGHT_COMPLEXITY_PENALTY: float = float(
    os.getenv("QUALITY_LIGHT_COMPLEXITY_PENALTY", "0.18")
)
# Spécialiste hors-domaine : se comporte comme un heavy générique (même base model).
QUALITY_SPECIALIST_OFF_DOMAIN: float = float(
    os.getenv("QUALITY_SPECIALIST_OFF_DOMAIN", "0.80")
)

# ────────────────────────────────────────────────────────────────────────────
# Phase 5 — Benchmark & calibration (harnais d'évaluation)
# ────────────────────────────────────────────────────────────────────────────

# Coût-proxy du ch.3 : temps_inférence (s) × taille_modèle (milliards de
# paramètres). La taille est une donnée publique du modèle ; tout modèle absent
# de la grille déclenche une erreur explicite (jamais d'estimation fabriquée).
# Le spécialiste de domaine (model_id "<heavy>#<domain>") partage la taille du
# modèle heavy de base : c'est le même modèle taggé d'un domaine.
MODEL_SIZE_B: dict[str, float] = {
    "meta-llama/llama-3.2-3b-instruct": 3.0,
    "anthropic/claude-sonnet-4.6": 200.0,
}

# Budgets SLA par défaut du benchmark InferRouter (latence ms, coût USD/appel).
# Larges par défaut pour que le routeur puisse choisir n'importe quel tier ;
# surchargeables par env pour étudier l'effet d'un SLA serré.
BENCH_L_MAX_MS: float = float(os.getenv("BENCH_L_MAX_MS", "1e9"))
BENCH_C_MAX: float = float(os.getenv("BENCH_C_MAX", "1e9"))

# Seed du tirage aléatoire (stratégie random, reproductibilité — règle dure).
BENCH_SEED: int = int(os.getenv("BENCH_SEED", "42"))
