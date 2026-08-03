import os

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# OpenRouter — LLM cibles
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Couple de modèles cibles. MODEL_LIGHT = qwen-2.5-72b-instruct — choisi NON
# parce qu'il est le meilleur léger (l'étude comparée de 6 modèles du 2026-07-23
# désigne deepseek-v3.2 : 0.53/0.52/0.58, plat, moins cher), mais parce que son
# profil DÉCROISSANT (0.64/0.39/0.32) rend le routage efficace. Finding central
# (cf. ch.5) : avec deepseek (plat, robuste) le routeur ne bat pas le hasard —
# aucun signal n'indique où le lourd aide le plus, l'écart léger/lourd étant
# uniforme. Avec qwen-72b, la faiblesse du léger suit la complexité, donc router
# les intents complexes vers le lourd cible exactement là où le léger flanche.
# Le bon léger n'est pas le plus fort, mais celui dont la faiblesse est
# prédictible. MODEL_HEAVY = claude-opus-4.8 (le test de robustesse a montré que
# Sonnet était trop proche du léger ; Opus crée l'écart que le routage exploite).
# Novita est exclu via provider={"ignore": ["novita"]} dans les appels API.
MODEL_LIGHT: str = os.getenv("MODEL_LIGHT", "qwen/qwen-2.5-72b-instruct")
MODEL_HEAVY: str = os.getenv("MODEL_HEAVY", "anthropic/claude-opus-4.8")
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
    "anthropic/claude-opus-4.8": {"prompt": 0.005, "completion": 0.025},
    "openai/gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "deepseek/deepseek-v3.2": {"prompt": 0.000269, "completion": 0.0004},
    "qwen/qwen3.5-flash-02-23": {"prompt": 0.000065, "completion": 0.00026},
    "google/gemini-2.5-flash-lite": {"prompt": 0.0001, "completion": 0.0004},
    "google/gemini-2.5-flash": {"prompt": 0.0003, "completion": 0.0025},
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
# (via OpenRouter). Fixé sur claude-sonnet-4.6, découplé de MODEL_HEAVY par
# NEUTRALITÉ : ni le léger (qwen-72b) ni le lourd (opus-4.8) évalués ne doit
# générer ses propres critères, sinon il serait juge et partie. Sonnet est un
# tiers fort, distinct des deux modèles du pool.
CHECKLIST_MODEL: str = os.getenv("CHECKLIST_MODEL", "anthropic/claude-sonnet-4.6")
# Borne de génération (tokens) pour la production de la checklist.
CHECKLIST_MAX_TOKENS: int = int(os.getenv("CHECKLIST_MAX_TOKENS", "512"))

# Jeu d'intents de base
INTENTS_SPIKE_PATH: str = os.getenv("INTENTS_SPIKE_PATH", "data/intents_spike.yaml")

# Estimateur de complexité sémantique — modèle d'embeddings.
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Génération du dataset d'intents.
# Modèle fort, mais FIGÉ plutôt que dérivé de MODEL_HEAVY : les 252 intents ont
# été produits le 2026-06-21 par claude-sonnet-4.6, quand MODEL_HEAVY valait
# encore Sonnet. Le basculement du lourd sur Opus (2026-07-22) rendrait une
# régénération non reproductible si ce paramètre suivait MODEL_HEAVY, alors que
# le mémoire attribue explicitement le jeu à Sonnet. Le figer préserve aussi la
# neutralité : le générateur du jeu reste distinct des deux tiers évalués.
GENERATION_MODEL: str = os.getenv("GENERATION_MODEL", "anthropic/claude-sonnet-4.6")
# Dataset cible produit par scripts/generate_dataset.py.
DATASET_PATH: str = os.getenv("DATASET_PATH", "data/intents_dataset.yaml")

# ────────────────────────────────────────────────────────────────────────────
# Routeur tri-critère (décision pure, sans réseau)
# ────────────────────────────────────────────────────────────────────────────

# Profils coût/latence par tier du pool, mesurés sur appels API réels.
# Léger (qwen2.5-72b) : coût moyen $0.000168/appel, latence P50 11.1s
# (calibration_api_light.json, 74 appels). Lourd (opus-4.8) : coût moyen
# $0.0285/appel (heavy_robustness.json, 74 appels, 2026-07-22), latence
# indicative ~15s. Rapport de coût réel léger/lourd ~170x.
POOL_LIGHT_COST: float = float(os.getenv("POOL_LIGHT_COST", "0.000168"))
POOL_LIGHT_LATENCY_MS: float = float(os.getenv("POOL_LIGHT_LATENCY_MS", "11076.0"))
POOL_HEAVY_COST: float = float(os.getenv("POOL_HEAVY_COST", "0.0285"))
POOL_HEAVY_LATENCY_MS: float = float(os.getenv("POOL_HEAVY_LATENCY_MS", "15000.0"))

# Domaines réseau spécialisés du pool (un modèle spécialisé par domaine).
POOL_DOMAINS: tuple[str, ...] = ("ran", "core", "security", "slice")

# Barème de qualité attendue (app/llm/policy.py). Toutes les valeurs dans
# [0, 1], calibrées sur la matrice qualité réelle (juge gemma2:9b, checklists
# neutres par claude-sonnet-4.6, léger qwen2.5-72b vs lourd claude-opus-4.8,
# n=74) :
#   simple  light=0.64  opus=0.94
#   medium  light=0.39  opus=0.86
#   complex light=0.32  opus=0.84
# La qualité du léger par complexité vient DIRECTEMENT de la mesure. qwen-72b a
# un profil DÉCROISSANT : sa faiblesse suit la complexité, ce qui crée le signal
# que le routeur exploite (router les complexes vers le lourd). C'est ce qui
# fait battre le hasard à InferRouter, là où un léger plat (deepseek) échouait.
QUALITY_LIGHT_BY_COMPLEXITY: dict[str, float] = {
    "simple": float(os.getenv("QUALITY_LIGHT_SIMPLE", "0.64")),
    "medium": float(os.getenv("QUALITY_LIGHT_MEDIUM", "0.39")),
    "complex": float(os.getenv("QUALITY_LIGHT_COMPLEX", "0.32")),
}
# Lourd (Opus) : moyenne des trois paliers mesurés (0.94/0.86/0.84). Traité
# comme plat par complexité (il reste fort partout ; la légère décroissance est
# dans le bruit du juge).
QUALITY_HEAVY_GENERIC: float = float(os.getenv("QUALITY_HEAVY_GENERIC", "0.88"))
# Effet mesuré d'un cadrage spécialiste, exprimé en écart sur le générique
# (exp_specialist.py). Mesuré sur claude-opus-4.8, juge gemma2:9b + RocketEval :
#   sur son domaine  : 0,962 contre 0,924 sur 15 intents RAN      -> +0,038
#   hors son domaine : 0,777 contre 0,914 sur 6 intents coeur     -> -0,137
# Ces valeurs remplacent deux constantes posées a priori (0,92 / 0,88). La
# pénalité hors domaine vaut 3,6 fois le gain : un pool de spécialistes ne
# vaut que si le routage par domaine est fiable.
SPECIALIST_ON_DOMAIN_DELTA: float = float(os.getenv("SPECIALIST_ON_DOMAIN_DELTA", "0.038"))
SPECIALIST_OFF_DOMAIN_DELTA: float = float(os.getenv("SPECIALIST_OFF_DOMAIN_DELTA", "-0.137"))

# Plancher de qualité minimale par criticité (q_min), consommé par le routeur
# (app/llm/router.py:select). Le routeur MINIMISE le coût sous contrainte
# q >= q_min (et non plus argmax q) : un intent critique exige un plancher plus
# haut, donc bascule plus volontiers vers le lourd. Calibré sur la matrice
# qualité 2026-07-22 (léger qwen-72b : simple 0.64 / medium 0.39 / complex 0.32,
# lourd Opus : ~0.88) pour que :
#   low  -> léger tant qu'il dépasse un plancher bas (priorité économie)
#   med  -> léger acceptable sur le simple seulement
#   high -> exige quasi toujours le lourd (priorité qualité)
# Seuils surchargeables par env pour tracer la sensibilité au plancher.
QMIN_BY_CRITICALITY: dict[str, float] = {
    "low": float(os.getenv("QMIN_LOW", "0.35")),
    "med": float(os.getenv("QMIN_MED", "0.50")),
    "high": float(os.getenv("QMIN_HIGH", "0.70")),
}

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
    # Tailles Claude non publiées : estimations. Opus > Sonnet (le tarif API
    # est ~1.67x), estimée à 340 Mds. Le coût-proxy (temps × taille) est de
    # toute façon secondaire face au coût $ réel désormais mesuré.
    "anthropic/claude-opus-4.8": 340.0,
    "qwen2.5:14b-instruct": 14.0,
    "qwen/qwen-2.5-72b-instruct": 72.0,
    # DeepSeek V3.2 est un MoE : ~37 Mds de params ACTIFS par token (la taille
    # qui compte pour le coût de calcul), estimation. Le coût-proxy reste
    # secondaire face au coût $ réel mesuré.
    "deepseek/deepseek-v3.2": 37.0,
}

# Budgets SLA par défaut du benchmark InferRouter (latence ms, coût USD/appel).
# Larges par défaut pour que le routeur puisse choisir n'importe quel tier ;
# surchargeables par env pour étudier l'effet d'un SLA serré.
BENCH_L_MAX_MS: float = float(os.getenv("BENCH_L_MAX_MS", "1e9"))
BENCH_C_MAX: float = float(os.getenv("BENCH_C_MAX", "1e9"))

# Seed du tirage aléatoire (stratégie random, pour la reproductibilité).
BENCH_SEED: int = int(os.getenv("BENCH_SEED", "42"))
