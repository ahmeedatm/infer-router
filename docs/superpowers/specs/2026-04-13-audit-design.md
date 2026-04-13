# Audit Report — InferRouter (base pour InferRouter-LLM)

**Date** : 2026-04-13  
**Contexte** : Projet académique (Phases 1–7 complètes). Ce repo sera étendu pour le mémoire  
*InferRouter-LLM : Sélection dynamique de grands modèles de langage par estimation sémantique  
de complexité et évaluation automatique de qualité*.  
**Approche** : Audit complet code + infra (Approche B), extension in-place du repo existant.

---

## 1. État des lieux

### Ce qui fonctionne bien

Le noyau algorithmique est solide et bien découpé : chaque module correspond exactement à une
section du papier IEEE (`aap.py` → IV-A, `gpp.py` → IV-B, `threshold.py` → IV-C).
L'abstraction `QueueBackend` (Protocol) est une bonne fondation pluggable.
Les docstrings des modules algorithmes sont clairs et référencent le papier.

### Points critiques

| ID | Sévérité | Description |
|----|----------|-------------|
| C1 | Bloquant | `main.py` (214 lignes) mélange lifespan, routes HTTP et construction du payload enrichi |
| C2 | Bloquant | `worker.py` (224 lignes) mélange routing decision, inference call et result storage |
| C3 | Bloquant | Aucun test — zéro fichier `test_*.py` dans le repo |
| C4 | Bloquant | Redis keys éparpillées entre `arrival.py`, `mu.py`, `threshold.py`, `aap.py` — pas de source unique de vérité |
| C5 | Bloquant | `MU_WINDOW`, `LAMBDA_WINDOW_S`, `K_MAX` hardcodés dans les modules plutôt que dans `config.py` |
| C6 | Qualité | `requirements.txt` mélange dépendances épinglées et non-épinglées (`matplotlib>=3.9.0`, etc.) |
| C7 | Qualité | Pas de `.dockerignore` — `COPY . .` embarque `.venv/`, 100+ JPEGs, `latex/` dans l'image Docker |
| C8 | Qualité | `CLIENT_CALLBACK_URL` hardcodé sur `host.docker.internal` (macOS uniquement, cassé sur Linux) |
| C9 | Qualité | `TODO.md` désynchronisé — Phase 7 marquée `[ ]` mais entièrement implémentée |
| C10 | Qualité | Pas de `.env.example` — impossible de configurer sans lire `config.py` ligne par ligne |

---

## 2. To-Do List priorisée

### P0 — Bloquant pour l'extension LLM

| # | Action | Fichier(s) |
|---|--------|------------|
| P0-1 | Extraire la construction du payload enrichi vers `app/request_builder.py` | `main.py` |
| P0-2 | Extraire la persistance des résultats vers `app/result_store.py` | `worker.py` |
| P0-3 | Créer `app/redis_keys.py` — centraliser toutes les Redis keys | `arrival.py`, `mu.py`, `threshold.py`, `aap.py` |
| P0-4 | Migrer `MU_WINDOW`, `LAMBDA_WINDOW_S`, `K_MAX` dans `config.py` avec override env var | `mu.py`, `arrival.py`, `threshold.py` |
| P0-5 | Créer `.env.example` avec toutes les variables documentées | (nouveau) |
| P0-6 | Créer `.dockerignore` excluant `.venv/`, `data/`, `latex/`, `traffic_des_clients/`, `*.pdf` | (nouveau) |

### P1 — Qualité académique

| # | Action | Fichier(s) |
|---|--------|------------|
| P1-1 | Tests unitaires pour `gpp.py`, `threshold.py`, `aap.py` (fonctions pures en priorité) | `tests/unit/` |
| P1-2 | Test d'intégration minimal pour `POST /new_pod_run_model` avec Redis mocké | `tests/integration/` |
| P1-3 | Épingler toutes les dépendances (`pip freeze > requirements.txt`) | `requirements.txt` |
| P1-4 | Mettre à jour `TODO.md` : cocher Phase 7, ajouter section Phase LLM | `TODO.md` |
| P1-5 | Corriger `CLIENT_CALLBACK_URL` : valeur par défaut `""` ou `http://localhost:5002/...` | `config.py`, `docker-compose.yml` |

### P2 — Hygiène

| # | Action | Fichier(s) |
|---|--------|------------|
| P2-1 | Renommer `traffic_des_clients/` → `scripts/traffic/` (cohérence anglais) | repo root |
| P2-2 | Ajouter `healthcheck` pour `model-fast` et `model-accurate` dans `docker-compose.yml` | `docker-compose.yml` |
| P2-3 | Ajouter `restart: unless-stopped` sur le service `api` | `docker-compose.yml` |
| P2-4 | Supprimer `flask` de `requirements.txt` (non utilisé) | `requirements.txt` |
| P2-5 | Vérifier et supprimer `annotated-doc` si inutilisé | `requirements.txt` |

---

## 3. Structure de dossier cible

```
infer-router/
│
├── app/
│   ├── __init__.py
│   ├── config.py              # Toutes les env vars + constantes (MU_WINDOW, LAMBDA_WINDOW_S, K_MAX…)
│   ├── redis_keys.py          # Source unique de vérité pour toutes les Redis keys
│   ├── models.py              # Pydantic schemas
│   ├── request_builder.py     # Construction du payload enrichi (sensor_id, timestamp, image_size)
│   ├── result_store.py        # Persistance des résultats dans Redis
│   ├── worker.py              # Boucle principale (allégée)
│   ├── main.py                # FastAPI app + lifespan (allégé)
│   │
│   ├── api/                   # Routes HTTP isolées
│   │   ├── __init__.py
│   │   ├── inference.py       # POST /new_pod_run_model, GET /results, GET /export
│   │   ├── monitoring.py      # GET /config, GET /accuracy, GET /scenarios, GET /health
│   │   └── dashboard.py       # GET /dashboard
│   │
│   ├── routing/               # Noyau algorithmique InferRouter
│   │   ├── __init__.py
│   │   ├── aap.py             # Anti-Idling Accuracy Profiling
│   │   ├── gpp.py             # Gold-Pair Prioritizing
│   │   └── threshold.py       # Waiting-Based Threshold Control
│   │
│   ├── metrics/               # Mesure des paramètres système
│   │   ├── __init__.py
│   │   ├── arrival.py         # Tracker λ (taux d'arrivée)
│   │   └── mu.py              # Tracker μ (taux de service par modèle)
│   │
│   └── queue/                 # Abstraction queue (inchangé)
│       ├── __init__.py
│       ├── base.py
│       ├── redis_backend.py
│       └── rabbitmq_backend.py
│
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_gpp.py
│   │   ├── test_threshold.py
│   │   └── test_aap.py
│   └── integration/
│       └── test_api.py
│
├── scripts/
│   ├── traffic_client.py
│   ├── plot_results.py
│   └── generate_report.py
│
├── data/
│   ├── bench/
│   └── plots/
│
├── docs/
│   └── redis_schema.md        # Toutes les clés Redis documentées
│
├── .env.example
├── .dockerignore
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── requirements.txt
├── README.md
└── CLAUDE.md
```

### Extension LLM (ajout futur)

Pour InferRouter-LLM, deux nouveaux modules viendront se brancher sur `app/routing/` :

```
app/
├── complexity/
│   └── estimator.py           # Estimation sémantique de complexité du prompt
└── quality/
    └── evaluator.py           # Évaluation automatique de qualité de la réponse LLM
```

---

## 4. Principes directeurs pour l'extension LLM

1. **`app/routing/` est le seul endroit à modifier** pour changer la logique de décision.  
   AAP → remplacé par un profiler de qualité LLM.  
   GPP → adapté avec une métrique de complexité sémantique au lieu de α.  
   Threshold → réutilisable tel quel (λ et μ restent valides pour les LLMs).

2. **`app/redis_keys.py` est la source de vérité** — toute nouvelle clé LLM (`complexity:...`, `quality:...`) doit y être déclarée.

3. **`config.py` est le seul point de configuration** — aucun paramètre numérique ne doit vivre dans un module métier.

4. **Tests en premier** — chaque nouveau module LLM (`estimator.py`, `evaluator.py`) doit avoir ses tests unitaires avant l'implémentation.
