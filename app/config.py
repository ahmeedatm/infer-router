import os

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# OpenRouter — LLM cibles
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Couple de modèles cibles (ajustables). MODEL_LIGHT = qwen2.5-72b-instruct
# (OpenRouter), calibré le 2026-07-21 : parité avec le heavy sur les intents
# simples (n=26, écart -0.04), confirmant à l'identique qwen2.5:14b-instruct
# (local, testé d'abord, écart -0.08) là où llama-3.2-3b et gpt-4o-mini
# restaient nettement en retrait. Le 14B n'étant pas hébergé sur OpenRouter,
# le 72B est retenu pour la mesure finale : latence/coût mesurés en conditions
# API réelles, sans dépendre du matériel de développement (cf. LOG.md
# 2026-07-21). Le fournisseur Novita rejette ce modèle sur cet endpoint
# (HTTP 400) ; exclu via provider={"ignore": ["novita"]} dans les appels.
MODEL_LIGHT: str = os.getenv("MODEL_LIGHT", "qwen/qwen-2.5-72b-instruct")
MODEL_HEAVY: str = os.getenv("MODEL_HEAVY", "anthropic/claude-sonnet-4.6")
OPENROUTER_TIMEOUT_S: float = float(os.getenv("OPENROUTER_TIMEOUT_S", "60.0"))
# Budget de génération (cap de tokens de complétion) des LLM cibles.
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
    "qwen/qwen-2.5-72b-instruct": {"prompt": 0.00036, "completion": 0.0004},
}

# LLM-Juge local (Ollama)
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# Génération locale (modèle léger candidat via Ollama). Timeout large : un 7B
# sur MacBook Air peut mettre plusieurs minutes sur un intent complexe.
OLLAMA_GENERATION_TIMEOUT_S: float = float(os.getenv("OLLAMA_GENERATION_TIMEOUT_S", "600.0"))
MODEL_LIGHT_LOCAL: str = os.getenv("MODEL_LIGHT_LOCAL", "qwen2.5:7b-instruct")
# gemma2:9b par défaut (validé : 100% en discrimination grossière, cf.
# LOG.md 2026-06-21) ; gemma2:2b s'est montré peu fiable (40-50% d'accord) et
# ne doit plus être le défaut silencieux d'un script lancé sans variable.
JUDGE_MODEL: str = os.getenv("JUDGE_MODEL", "gemma2:9b")
# Modèle fort qui génère la checklist RocketEval spécifique à chaque intent
# (via OpenRouter). Réutilise le heavy par défaut.
CHECKLIST_MODEL: str = os.getenv("CHECKLIST_MODEL", MODEL_HEAVY)
# Borne de génération (tokens) pour la production de la checklist.
CHECKLIST_MAX_TOKENS: int = int(os.getenv("CHECKLIST_MAX_TOKENS", "512"))

# Jeu d'intents de base
INTENTS_SPIKE_PATH: str = os.getenv("INTENTS_SPIKE_PATH", "data/intents_spike.yaml")

# Estimateur de complexité sémantique — modèle d'embeddings.
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Génération du dataset d'intents.
# Modèle fort par défaut : la génération exige du réalisme et de la diversité.
GENERATION_MODEL: str = os.getenv("GENERATION_MODEL", MODEL_HEAVY)
# Dataset cible produit par scripts/generate_dataset.py.
DATASET_PATH: str = os.getenv("DATASET_PATH", "data/intents_dataset.yaml")

# ────────────────────────────────────────────────────────────────────────────
# Routeur tri-critère (décision pure, sans réseau)
# ────────────────────────────────────────────────────────────────────────────

# Profils coût/latence par tier du pool. Le light étant servi par
# l'API OpenRouter (qwen2.5-72b-instruct), coût et latence sont la moyenne
# mesurée sur 74 appels réels (calibration_api_light.json, 2026-07-21) :
# coût moyen $0.000168/appel, latence moyenne 11.1s. Mesure en conditions de
# service réelles, contrairement au 14B local (MacBook, non représentatif).
POOL_LIGHT_COST: float = float(os.getenv("POOL_LIGHT_COST", "0.000168"))
POOL_LIGHT_LATENCY_MS: float = float(os.getenv("POOL_LIGHT_LATENCY_MS", "11076.0"))
POOL_HEAVY_COST: float = float(os.getenv("POOL_HEAVY_COST", "0.018"))
POOL_HEAVY_LATENCY_MS: float = float(os.getenv("POOL_HEAVY_LATENCY_MS", "1200.0"))

# Domaines réseau spécialisés du pool (un modèle spécialisé par domaine).
POOL_DOMAINS: tuple[str, ...] = ("ran", "core", "security", "slice")

# Barème de qualité attendue (app/llm/policy.py). Toutes les valeurs dans
# [0, 1]. QUALITY_HEAVY_GENERIC et QUALITY_LIGHT_BASE/PENALTY calibrés sur la
# matrice qualité réelle du 2026-07-21 (juge gemma2:9b, qwen2.5-72b-instruct
# API vs claude-sonnet-4.6), qui confirme celle du 14B local (2026-07-20) :
#   simple  n=26  light=0.64  heavy=0.60
#   medium  n=24  light=0.39  heavy=0.50
#   complex n=24  light=0.32  heavy=0.24  (juge non fiable sur ce régime,
#     cf. docs/analyses/2026-07-20-paires-complexes-14b-vs-heavy.md —
#     valeur EXCLUE de la calibration, on garde l'extrapolation linéaire)
# QUALITY_HEAVY_GENERIC = moyenne des paliers fiables (simple, medium) :
# le modèle reste plat par complexité (limite connue, pas recalibrée ici).
QUALITY_HEAVY_GENERIC: float = float(os.getenv("QUALITY_HEAVY_GENERIC", "0.55"))
# QUALITY_LIGHT_BASE = qualité mesurée sur simple.
QUALITY_LIGHT_BASE: float = float(os.getenv("QUALITY_LIGHT_BASE", "0.64"))
# Pénalité par cran = chute mesurée simple->medium (0.64-0.39=0.25) ; le palier
# complex measuré (0.32) n'est PAS utilisé pour caler ce paramètre (juge non
# fiable à ce niveau), on extrapole donc la pénalité linéaire au-delà.
QUALITY_LIGHT_COMPLEXITY_PENALTY: float = float(
    os.getenv("QUALITY_LIGHT_COMPLEXITY_PENALTY", "0.25")
)
# Spécialistes de domaine : jamais mesurés (pool à 1 spécialiste par domaine
# non instancié dans les runs de calibration/benchmark actuels) ; valeurs de
# prototype non calibrées, cf. app/llm/policy.py.
QUALITY_SPECIALIST_ON_DOMAIN: float = float(os.getenv("QUALITY_SPECIALIST_ON_DOMAIN", "0.92"))
# Doit valoir QUALITY_HEAVY_GENERIC par construction (même modèle de base,
# sans bonus de domaine) : synchroniser si l'un des deux est recalibré.
QUALITY_SPECIALIST_OFF_DOMAIN: float = float(
    os.getenv("QUALITY_SPECIALIST_OFF_DOMAIN", "0.55")
)

# ────────────────────────────────────────────────────────────────────────────
# Benchmark & calibration (harnais d'évaluation)
# ────────────────────────────────────────────────────────────────────────────

# Coût-proxy : temps_inférence (s) × taille_modèle (milliards de
# paramètres). La taille est une donnée publique du modèle ; tout modèle absent
# de la grille déclenche une erreur explicite (jamais d'estimation fabriquée).
# Le spécialiste de domaine (model_id "<heavy>#<domain>") partage la taille du
# modèle heavy de base : c'est le même modèle taggé d'un domaine.
MODEL_SIZE_B: dict[str, float] = {
    "meta-llama/llama-3.2-3b-instruct": 3.0,
    "anthropic/claude-sonnet-4.6": 200.0,
    "qwen2.5:14b-instruct": 14.0,
    "qwen/qwen-2.5-72b-instruct": 72.0,
}

# Budgets SLA par défaut du benchmark InferRouter (latence ms, coût USD/appel).
# Larges par défaut pour que le routeur puisse choisir n'importe quel tier ;
# surchargeables par env pour étudier l'effet d'un SLA serré.
BENCH_L_MAX_MS: float = float(os.getenv("BENCH_L_MAX_MS", "1e9"))
BENCH_C_MAX: float = float(os.getenv("BENCH_C_MAX", "1e9"))

# Seed du tirage aléatoire (stratégie random, pour la reproductibilité).
BENCH_SEED: int = int(os.getenv("BENCH_SEED", "42"))
