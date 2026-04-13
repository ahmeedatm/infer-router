# Audit Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Appliquer les corrections P0/P1/P2 de l'audit pour rendre le repo propre et prêt pour l'extension InferRouter-LLM.

**Architecture:** Les tâches P0 refactorisent la structure interne (extraction de modules, centralisation des clés Redis, migration des constantes). Les tâches P1 ajoutent les tests et corrigent la reproductibilité. Les tâches P2 nettoient l'infrastructure Docker et le repo.

**Tech Stack:** Python 3.11, FastAPI, Redis (asyncio), pytest, pytest-asyncio, httpx

---

## Carte des fichiers

| Action | Fichier | Responsabilité après refactoring |
|--------|---------|----------------------------------|
| Créer | `app/redis_keys.py` | Source unique de vérité pour toutes les Redis keys |
| Créer | `app/request_builder.py` | Construction du payload enrichi (sensor_id, timestamp, image_size) |
| Créer | `app/result_store.py` | Persistance des résultats dans Redis |
| Créer | `.env.example` | Documentation des variables d'environnement |
| Créer | `.dockerignore` | Exclusion des artefacts de l'image Docker |
| Créer | `tests/__init__.py` | Package tests |
| Créer | `tests/unit/__init__.py` | Package tests unitaires |
| Créer | `tests/unit/test_gpp.py` | Tests unitaires GPP |
| Créer | `tests/unit/test_threshold.py` | Tests unitaires Threshold FSM |
| Créer | `tests/unit/test_aap.py` | Tests unitaires AAP (fonctions pures) |
| Créer | `tests/integration/__init__.py` | Package tests intégration |
| Créer | `tests/integration/test_api.py` | Test intégration POST /new_pod_run_model |
| Modifier | `app/config.py` | Ajouter MU_WINDOW, LAMBDA_WINDOW_S, K_MAX + supprimer INFERENCE_QUEUE_KEY, RESULTS_KEY_PREFIX, ACCURACY_KEY_PREFIX |
| Modifier | `app/arrival.py` | Importer ARRIVALS_KEY, LAMBDA_KEY depuis redis_keys + LAMBDA_WINDOW_S depuis config |
| Modifier | `app/mu.py` | Importer LATENCIES_KEY_PREFIX, MU_KEY_PREFIX depuis redis_keys + MU_WINDOW depuis config |
| Modifier | `app/threshold.py` | Importer K_ACTIVE_KEY depuis redis_keys + K_MAX, K_MIN depuis config |
| Modifier | `app/aap.py` | Importer AAP_WINDOW_KEY_PREFIX depuis redis_keys |
| Modifier | `app/dashboard.py` | Importer RESULTS_KEY_PREFIX, ACCURACY_KEY_PREFIX depuis redis_keys |
| Modifier | `app/main.py` | Utiliser request_builder + importer depuis redis_keys |
| Modifier | `app/worker.py` | Utiliser result_store |
| Modifier | `requirements.txt` | Épingler toutes les dépendances + ajouter pytest/pytest-asyncio/httpx |
| Modifier | `docker-compose.yml` | Corriger CLIENT_CALLBACK_URL + healthchecks + restart policy |
| Modifier | `TODO.md` | Cocher Phase 7, ajouter Phase LLM |

---

## Task 1 : Créer `app/redis_keys.py` (P0-3)

**Files:**
- Create: `app/redis_keys.py`

- [ ] **Step 1 : Créer le fichier**

```python
# app/redis_keys.py
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
```

- [ ] **Step 2 : Mettre à jour `app/arrival.py`**

Remplacer les deux constantes locales par des imports depuis `redis_keys` :

```python
# app/arrival.py — remplacer les lignes 17-18 :
# AVANT :
# LAMBDA_WINDOW_S: float = 5.0
# ARRIVALS_KEY: str = "metrics:arrivals"
# LAMBDA_KEY: str = "metrics:lambda"

# APRÈS — ajouter en haut du fichier (après les imports stdlib) :
from app.config import LAMBDA_WINDOW_S
from app.redis_keys import ARRIVALS_KEY, LAMBDA_KEY
```

Le reste du fichier `arrival.py` reste identique — les constantes ont le même nom, seule leur source change.

- [ ] **Step 3 : Mettre à jour `app/mu.py`**

```python
# app/mu.py — remplacer les lignes 14-15 :
# AVANT :
# MU_WINDOW: int = 50
# LATENCIES_KEY_PREFIX: str = "metrics:latencies"
# MU_KEY_PREFIX: str = "metrics:mu"

# APRÈS :
from app.config import MU_WINDOW
from app.redis_keys import LATENCIES_KEY_PREFIX, MU_KEY_PREFIX
```

- [ ] **Step 4 : Mettre à jour `app/threshold.py`**

```python
# app/threshold.py — remplacer les lignes 29-31 :
# AVANT :
# K_ACTIVE_KEY: str = "metrics:k_active"
# K_MIN: int = 1
# K_MAX: int = 2

# APRÈS :
from app.config import K_MAX, K_MIN
from app.redis_keys import K_ACTIVE_KEY
```

- [ ] **Step 5 : Mettre à jour `app/aap.py`**

```python
# app/aap.py — remplacer la ligne 30 :
# AVANT :
# AAP_WINDOW_KEY_PREFIX: str = "aap:window"

# APRÈS :
from app.redis_keys import AAP_WINDOW_KEY_PREFIX
```

- [ ] **Step 6 : Mettre à jour `app/dashboard.py`**

Dans les imports de `dashboard.py`, remplacer :
```python
# AVANT (lignes 11-18 de dashboard.py) :
from app.config import (
    ACCURATE_MODEL_NAME,
    ACCURACY_KEY_PREFIX,
    C_COEFFICIENT,
    FAST_MODEL_NAME,
    OMEGA,
    RESULTS_KEY_PREFIX,
    TAU,
)

# APRÈS :
from app.config import (
    ACCURATE_MODEL_NAME,
    C_COEFFICIENT,
    FAST_MODEL_NAME,
    OMEGA,
    TAU,
)
from app.redis_keys import ACCURACY_KEY_PREFIX, RESULTS_KEY_PREFIX
```

- [ ] **Step 7 : Mettre à jour `app/main.py`**

Dans les imports de `main.py`, remplacer :
```python
# AVANT (dans le bloc import app.config) :
from app.config import (
    ...
    ACCURACY_KEY_PREFIX,
    ...
    INFERENCE_QUEUE_KEY,
    ...
    RESULTS_KEY_PREFIX,
    ...
)

# APRÈS — supprimer ACCURACY_KEY_PREFIX, INFERENCE_QUEUE_KEY, RESULTS_KEY_PREFIX
# du bloc import app.config et ajouter :
from app.redis_keys import (
    ACCURACY_KEY_PREFIX,
    INFERENCE_QUEUE_KEY,
    RESULTS_KEY_PREFIX,
    PUSH_LATENCY_KEY_PREFIX,
)
```

Et dans la fonction `receive_data` (ligne ~112 de main.py), remplacer :
```python
# AVANT :
    await app.state.redis.set(
        f"push_latency:{enriched['sensor_id']}",

# APRÈS :
    await app.state.redis.set(
        f"{PUSH_LATENCY_KEY_PREFIX}:{enriched['sensor_id']}",
```

- [ ] **Step 8 : Mettre à jour `app/worker.py`**

Dans les imports de `worker.py`, remplacer :
```python
# AVANT (dans le bloc import app.config) :
from app.config import (
    ...
    ACCURACY_KEY_PREFIX,
    ...
    RESULTS_KEY_PREFIX,
    ...
)

# APRÈS — supprimer ACCURACY_KEY_PREFIX et RESULTS_KEY_PREFIX du bloc config
# et ajouter :
from app.redis_keys import (
    ACCURACY_KEY_PREFIX,
    PUSH_LATENCY_KEY_PREFIX,
    RESULTS_KEY_PREFIX,
)
```

Et dans la fonction `process_inference` (ligne ~137 de worker.py), remplacer :
```python
# AVANT :
            push_key = f"push_latency:{sensor_id}"

# APRÈS :
            push_key = f"{PUSH_LATENCY_KEY_PREFIX}:{sensor_id}"
```

- [ ] **Step 9 : Supprimer les constantes déplacées de `app/config.py`**

Supprimer de `config.py` les lignes :
```python
# Supprimer ces 3 lignes :
INFERENCE_QUEUE_KEY: str = "inference_queue"
RESULTS_KEY_PREFIX: str = "inference_results"
ACCURACY_KEY_PREFIX: str = "accuracy"
```

- [ ] **Step 10 : Vérifier que l'app démarre**

```bash
make run
# Expected: uvicorn démarre sans ImportError sur http://0.0.0.0:8000
# Ctrl+C pour arrêter
```

- [ ] **Step 11 : Commit**

```bash
git add app/redis_keys.py app/arrival.py app/mu.py app/threshold.py app/aap.py app/dashboard.py app/main.py app/worker.py app/config.py
git commit -m "refactor: centralise all Redis keys in app/redis_keys.py"
```

---

## Task 2 : Migrer les constantes algorithmiques dans `config.py` (P0-4)

**Files:**
- Modify: `app/config.py`
- Modify: `app/mu.py`
- Modify: `app/arrival.py`
- Modify: `app/threshold.py`

- [ ] **Step 1 : Ajouter les constantes dans `app/config.py`**

Ajouter à la fin de `config.py` :

```python
# ── Algorithmic parameters (overridable for testing / tuning) ──────────────
MU_WINDOW: int = int(os.getenv("MU_WINDOW", "50"))
# Number of latency samples kept per model for μ computation

LAMBDA_WINDOW_S: float = float(os.getenv("LAMBDA_WINDOW_S", "5.0"))
# Sliding window width (seconds) for arrival rate λ estimation

K_MIN: int = 1
K_MAX: int = int(os.getenv("K_MAX", "2"))
# Min/max number of active models in the Threshold FSM
```

- [ ] **Step 2 : Supprimer `MU_WINDOW` de `app/mu.py`**

La ligne `MU_WINDOW: int = 50` en haut de `mu.py` est maintenant redondante (l'import depuis `app.config` est déjà en place après Task 1). S'assurer qu'elle est supprimée.

- [ ] **Step 3 : Supprimer `LAMBDA_WINDOW_S` de `app/arrival.py`**

La ligne `LAMBDA_WINDOW_S: float = 5.0` en haut de `arrival.py` est maintenant redondante. S'assurer qu'elle est supprimée.

- [ ] **Step 4 : Supprimer `K_MIN` et `K_MAX` de `app/threshold.py`**

Les lignes `K_MIN: int = 1` et `K_MAX: int = 2` en haut de `threshold.py` sont maintenant redondantes. S'assurer qu'elles sont supprimées.

- [ ] **Step 5 : Vérifier que l'app démarre**

```bash
make run
# Expected: démarre sans erreur. Ctrl+C
```

- [ ] **Step 6 : Commit**

```bash
git add app/config.py app/mu.py app/arrival.py app/threshold.py
git commit -m "refactor: migrate MU_WINDOW, LAMBDA_WINDOW_S, K_MAX/K_MIN to config.py"
```

---

## Task 3 : Créer `app/request_builder.py` + alléger `main.py` (P0-1)

**Files:**
- Create: `app/request_builder.py`
- Modify: `app/main.py`

- [ ] **Step 1 : Créer `app/request_builder.py`**

```python
# app/request_builder.py
"""Build the enriched inference payload from an incoming InferenceRequest.

Separates payload construction from HTTP routing so main.py stays focused
on request/response wiring, and future LLM extensions can add their own
enrichment (e.g. prompt complexity score) without touching main.py.
"""
from __future__ import annotations

import base64
import time
import uuid

from app.models import InferenceRequest


def build_enriched_payload(request: InferenceRequest) -> dict:
    """Return a JSON-serialisable dict ready to push onto the queue.

    Adds:
      - sensor_id: unique request identifier (UUID4)
      - timestamp: epoch seconds at the moment the request is received
      - image_size: decoded byte length of the image
    """
    image_bytes = base64.b64decode(request.image + "==")
    return {
        **request.model_dump(),
        "sensor_id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "image_size": len(image_bytes),
    }
```

- [ ] **Step 2 : Mettre à jour `app/main.py`**

Ajouter l'import en haut de `main.py` :
```python
from app.request_builder import build_enriched_payload
```

Remplacer le corps de `receive_data` (lignes ~102-122 de main.py) :

```python
@app.post("/new_pod_run_model", response_model=QueuedResponse)
async def receive_data(data: InferenceRequest):
    enriched = build_enriched_payload(data)
    push_latency_ms = await app.state.queue.push(json.dumps(enriched))
    await app.state.redis.set(
        f"{PUSH_LATENCY_KEY_PREFIX}:{enriched['sensor_id']}",
        str(round(push_latency_ms, 3)),
        ex=300,
    )
    await record_arrival(app.state.redis)
    logger.info(
        "Queued sensor_id=%s [scenario=%s] image_size=%d push_latency=%.2fms",
        enriched["sensor_id"], data.scenario, enriched["image_size"], push_latency_ms,
    )
    return QueuedResponse(status="queued", scenario=data.scenario)
```

Supprimer de `main.py` les imports devenus inutiles dans cette fonction :
```python
# Supprimer du bloc d'imports stdlib :
import base64
import uuid
```

(Vérifier que `base64` et `uuid` ne sont plus utilisés ailleurs dans `main.py` avant de les supprimer.)

- [ ] **Step 3 : Vérifier que l'app démarre et répond**

```bash
make run
# Dans un autre terminal :
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}
```

- [ ] **Step 4 : Commit**

```bash
git add app/request_builder.py app/main.py
git commit -m "refactor: extract payload enrichment into app/request_builder.py"
```

---

## Task 4 : Créer `app/result_store.py` + alléger `worker.py` (P0-2)

**Files:**
- Create: `app/result_store.py`
- Modify: `app/worker.py`

- [ ] **Step 1 : Créer `app/result_store.py`**

```python
# app/result_store.py
"""Persist an inference result dict to Redis.

Extracted from worker.py so the storage concern is separate from the
routing loop. Future LLM results (with quality scores, prompt metadata)
will be stored here without modifying the worker.
"""
from __future__ import annotations

import json

from redis.asyncio import Redis

from app.config import RESULTS_MAX_LEN
from app.redis_keys import RESULTS_KEY_PREFIX


async def store_result(redis: Redis, scenario: str, result_dict: dict) -> None:
    """LPUSH result_dict into the scenario list, trimmed to RESULTS_MAX_LEN."""
    key = f"{RESULTS_KEY_PREFIX}:{scenario}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lpush(key, json.dumps(result_dict))
        pipe.ltrim(key, 0, RESULTS_MAX_LEN - 1)
        await pipe.execute()
```

- [ ] **Step 2 : Mettre à jour `app/worker.py`**

Ajouter l'import :
```python
from app.result_store import store_result
```

Remplacer le bloc de stockage dans `process_inference` (lignes ~207-211 de worker.py) :

```python
# AVANT :
            results_key = f"{RESULTS_KEY_PREFIX}:{scenario}"
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lpush(results_key, json.dumps(result_dict))
                pipe.ltrim(results_key, 0, RESULTS_MAX_LEN - 1)
                await pipe.execute()

# APRÈS :
            await store_result(redis_client, scenario, result_dict)
```

Supprimer de `worker.py` les imports devenus inutiles :
```python
# Supprimer du bloc import app.config :
RESULTS_KEY_PREFIX,
RESULTS_MAX_LEN,
```

Et supprimer l'import stdlib `json` seulement si json n'est plus utilisé ailleurs dans worker.py.
(Vérifier : `json.loads` est toujours utilisé ligne ~126 — garder `import json`.)

- [ ] **Step 3 : Vérifier que l'app démarre**

```bash
make run
# Expected: démarre sans erreur. Ctrl+C
```

- [ ] **Step 4 : Commit**

```bash
git add app/result_store.py app/worker.py
git commit -m "refactor: extract result persistence into app/result_store.py"
```

---

## Task 5 : Créer `.env.example` et `.dockerignore` (P0-5, P0-6)

**Files:**
- Create: `.env.example`
- Create: `.dockerignore`

- [ ] **Step 1 : Créer `.env.example`**

```bash
# .env.example
# Copy this file to .env and fill in values for local development.
# Docker Compose reads .env automatically when present.

# ── Infrastructure ──────────────────────────────────────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379

# ── Routing ─────────────────────────────────────────────────────────────────
# Valid values: infer-router | always-fast | always-accurate
ROUTING_STRATEGY=infer-router

# Queue backend (redis | rabbitmq)
QUEUE_BACKEND=redis
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/

# ── Model endpoints ──────────────────────────────────────────────────────────
FAST_MODEL_URL=http://model-fast:5002/new_pod_run_model
ACCURATE_MODEL_URL=http://model-accurate:5002/new_pod_run_model

# Callback URL for model containers to return results.
# macOS Docker: use host.docker.internal
# Linux Docker: use the host's LAN IP (e.g. 192.168.1.x) or host-gateway
CLIENT_CALLBACK_URL=http://host.docker.internal:5002/save_result

# ── InferRouter algorithm ────────────────────────────────────────────────────
TAU=5.0          # SLA waiting-time budget (seconds)
C_COEFFICIENT=1.0
OMEGA=1.0
AAP_WINDOW=10

# ── Tunable algorithmic parameters ──────────────────────────────────────────
MU_WINDOW=50          # Latency samples kept per model for μ computation
LAMBDA_WINDOW_S=5.0   # Arrival rate sliding window (seconds)
K_MAX=2               # Max active models in Threshold FSM

# ── Observability ────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
```

- [ ] **Step 2 : Créer `.dockerignore`**

```
# .dockerignore
# Prevents bloat from dev artefacts being copied into the Docker image.

# Python virtual environment (re-installed in Dockerfile via pip)
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.Python

# Test artefacts
.pytest_cache/
.coverage
htmlcov/

# Dataset and benchmark outputs (not needed at runtime)
data/images/
data/plots/
data/bench/

# Traffic client legacy directory
traffic_des_clients/

# LaTeX and presentation sources
latex/
presentation/

# macOS
.DS_Store

# Git
.git/
.gitignore

# IDE
.vscode/
.idea/

# Docs (not needed at runtime)
docs/
*.pdf
*.md
```

- [ ] **Step 3 : Commit**

```bash
git add .env.example .dockerignore
git commit -m "chore: add .env.example and .dockerignore"
```

---

## Task 6 : Tests unitaires `app/gpp.py` (P1-1)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_gpp.py`

- [ ] **Step 1 : Ajouter pytest + pytest-asyncio dans `requirements.txt`**

Ajouter à la fin de `requirements.txt` :
```
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

Installer :
```bash
.venv/bin/pip install pytest pytest-asyncio
```

- [ ] **Step 2 : Créer les fichiers `__init__.py`**

```bash
touch tests/__init__.py tests/unit/__init__.py
```

- [ ] **Step 3 : Écrire les tests (RED)**

```python
# tests/unit/test_gpp.py
import math
import pytest
from app.gpp import compute_priority, rank_models, ModelPriority


class TestComputePriority:
    def test_basic_formula(self):
        # p = alpha + omega * c / mu = 0.0 + 1.0 * 1.0 / 2.0 = 0.5
        assert compute_priority(alpha_i=0.0, mu_i=2.0, c=1.0, omega=1.0) == pytest.approx(0.5)

    def test_gold_standard_alpha_zero(self):
        # Gold standard: alpha=0, p = omega*c/mu
        assert compute_priority(alpha_i=0.0, mu_i=1.0, c=1.0, omega=1.0) == pytest.approx(1.0)

    def test_zero_mu_returns_inf(self):
        assert compute_priority(alpha_i=0.5, mu_i=0.0, c=1.0, omega=1.0) == math.inf

    def test_negative_mu_returns_inf(self):
        assert compute_priority(alpha_i=0.0, mu_i=-1.0, c=1.0, omega=1.0) == math.inf

    def test_higher_inaccuracy_raises_priority_value(self):
        p_accurate = compute_priority(alpha_i=0.0, mu_i=1.0, c=1.0, omega=1.0)
        p_inaccurate = compute_priority(alpha_i=0.5, mu_i=1.0, c=1.0, omega=1.0)
        assert p_inaccurate > p_accurate

    def test_faster_model_lowers_priority_value(self):
        p_slow = compute_priority(alpha_i=0.1, mu_i=1.0, c=1.0, omega=1.0)
        p_fast = compute_priority(alpha_i=0.1, mu_i=5.0, c=1.0, omega=1.0)
        assert p_fast < p_slow


class TestRankModels:
    def test_returns_all_models(self):
        models = [("Fast", "http://fast"), ("Accurate", "http://accurate")]
        ranked = rank_models(models, {"Fast": 0.1, "Accurate": 0.0}, {"Fast": 5.0, "Accurate": 1.0}, c=1.0, omega=1.0)
        assert len(ranked) == 2

    def test_sorted_ascending_priority(self):
        # Fast: p = 0.1 + 1.0/5.0 = 0.3
        # Accurate: p = 0.0 + 1.0/1.0 = 1.0
        # Fast has lower p → ranked first
        models = [("Fast", "http://fast"), ("Accurate", "http://accurate")]
        ranked = rank_models(models, {"Fast": 0.1, "Accurate": 0.0}, {"Fast": 5.0, "Accurate": 1.0}, c=1.0, omega=1.0)
        assert ranked[0].name == "Fast"
        assert ranked[1].name == "Accurate"

    def test_accurate_first_when_fast_very_inaccurate(self):
        # Fast: p = 0.9 + 1.0/5.0 = 1.1
        # Accurate: p = 0.0 + 1.0/1.0 = 1.0
        # Accurate has lower p → ranked first
        models = [("Fast", "http://fast"), ("Accurate", "http://accurate")]
        ranked = rank_models(models, {"Fast": 0.9, "Accurate": 0.0}, {"Fast": 5.0, "Accurate": 1.0}, c=1.0, omega=1.0)
        assert ranked[0].name == "Accurate"

    def test_model_priority_dataclass_fields(self):
        models = [("M1", "http://m1")]
        ranked = rank_models(models, {"M1": 0.2}, {"M1": 2.0}, c=1.0, omega=1.0)
        m = ranked[0]
        assert isinstance(m, ModelPriority)
        assert m.name == "M1"
        assert m.url == "http://m1"
        assert m.alpha == pytest.approx(0.2)
        assert m.mu == pytest.approx(2.0)
```

- [ ] **Step 4 : Lancer les tests — vérifier qu'ils passent**

```bash
.venv/bin/pytest tests/unit/test_gpp.py -v
# Expected: 10 tests PASSED
```

- [ ] **Step 5 : Commit**

```bash
git add tests/__init__.py tests/unit/__init__.py tests/unit/test_gpp.py requirements.txt
git commit -m "test: add unit tests for gpp.py"
```

---

## Task 7 : Tests unitaires `app/threshold.py` (P1-1 suite)

**Files:**
- Create: `tests/unit/test_threshold.py`

- [ ] **Step 1 : Écrire les tests (RED)**

```python
# tests/unit/test_threshold.py
import math
import pytest
from app.threshold import compute_waiting_time


class TestComputeWaitingTime:
    def test_zero_mu_returns_inf(self):
        assert compute_waiting_time(queue_length=5, mu_k=0.0, lambda_=1.0, tau=5.0) == math.inf

    def test_empty_queue_formula(self):
        # queue_length=1 → x=max(1,1)=1 → (1-1)/(2*mu) = 0
        # w = 0 + tau / (1 + exp(mu - lambda))
        # w = 5.0 / (1 + exp(1.0 - 0.5)) = 5.0 / (1 + exp(0.5))
        expected = 5.0 / (1 + math.exp(1.0 - 0.5))
        assert compute_waiting_time(queue_length=1, mu_k=1.0, lambda_=0.5, tau=5.0) == pytest.approx(expected)

    def test_larger_queue_increases_wait(self):
        w_small = compute_waiting_time(queue_length=2, mu_k=1.0, lambda_=0.5, tau=5.0)
        w_large = compute_waiting_time(queue_length=10, mu_k=1.0, lambda_=0.5, tau=5.0)
        assert w_large > w_small

    def test_high_arrival_rate_increases_wait(self):
        # lambda > mu → system stressed → higher w
        w_low = compute_waiting_time(queue_length=5, mu_k=2.0, lambda_=0.5, tau=5.0)
        w_high = compute_waiting_time(queue_length=5, mu_k=2.0, lambda_=3.0, tau=5.0)
        assert w_high > w_low

    def test_queue_length_zero_treated_as_one(self):
        # queue_length=0 → x=max(0,1)=1 → same as queue_length=1
        w_zero = compute_waiting_time(queue_length=0, mu_k=1.0, lambda_=0.5, tau=5.0)
        w_one = compute_waiting_time(queue_length=1, mu_k=1.0, lambda_=0.5, tau=5.0)
        assert w_zero == pytest.approx(w_one)

    def test_higher_mu_decreases_wait(self):
        w_slow = compute_waiting_time(queue_length=5, mu_k=0.5, lambda_=0.3, tau=5.0)
        w_fast = compute_waiting_time(queue_length=5, mu_k=2.0, lambda_=0.3, tau=5.0)
        assert w_fast < w_slow
```

- [ ] **Step 2 : Lancer les tests**

```bash
.venv/bin/pytest tests/unit/test_threshold.py -v
# Expected: 6 tests PASSED
```

- [ ] **Step 3 : Commit**

```bash
git add tests/unit/test_threshold.py
git commit -m "test: add unit tests for threshold.py"
```

---

## Task 8 : Tests unitaires `app/aap.py` (P1-1 suite)

**Files:**
- Create: `tests/unit/test_aap.py`

- [ ] **Step 1 : Écrire les tests (RED)**

```python
# tests/unit/test_aap.py
"""Tests for the pure/near-pure functions in aap.py.

_compare_results is a pure function — tested directly.
_update_accuracy_window uses Redis — tested with AsyncMock.
"""
import pytest
from unittest.mock import AsyncMock, patch, call
from app.aap import _compare_results, _update_accuracy_window


class TestCompareResults:
    def test_both_none_is_match(self):
        assert _compare_results(None, None) is True

    def test_gold_none_candidate_present_is_mismatch(self):
        assert _compare_results(None, {"class": "cat"}) is False

    def test_gold_present_candidate_none_is_mismatch(self):
        assert _compare_results({"class": "cat"}, None) is False

    def test_both_present_is_match(self):
        # Current PoC implementation: any two non-None results count as a match.
        # This is intentional — replace with IoU/class comparison for real detections.
        assert _compare_results({"class": "cat"}, {"class": "dog"}) is True

    def test_both_present_same_value_is_match(self):
        assert _compare_results({"class": "cat"}, {"class": "cat"}) is True


class TestUpdateAccuracyWindow:
    @pytest.mark.asyncio
    async def test_stores_accuracy_in_redis(self):
        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline.return_value = mock_pipe
        # Simulate a window with 2 matches out of 2
        mock_redis.lrange = AsyncMock(return_value=[b"1", b"1"])

        await _update_accuracy_window(mock_redis, "Fast-Model", match=True, window=10)

        mock_redis.set.assert_called_once()
        set_args = mock_redis.set.call_args[0]
        assert "accuracy:Fast-Model" in set_args[0]
        assert set_args[1] == "1.0"

    @pytest.mark.asyncio
    async def test_partial_accuracy(self):
        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline.return_value = mock_pipe
        # 1 match out of 2 = 0.5 accuracy
        mock_redis.lrange = AsyncMock(return_value=[b"1", b"0"])

        await _update_accuracy_window(mock_redis, "Fast-Model", match=False, window=10)

        set_args = mock_redis.set.call_args[0]
        assert set_args[1] == "0.5"
```

- [ ] **Step 2 : Ajouter `pytest-asyncio` config dans `pyproject.toml` (ou `pytest.ini`)**

Créer `pytest.ini` à la racine :
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3 : Lancer les tests**

```bash
.venv/bin/pytest tests/unit/test_aap.py -v
# Expected: 7 tests PASSED
```

- [ ] **Step 4 : Commit**

```bash
git add tests/unit/test_aap.py pytest.ini
git commit -m "test: add unit tests for aap.py"
```

---

## Task 9 : Test d'intégration `POST /new_pod_run_model` (P1-2)

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_api.py`

- [ ] **Step 1 : Créer `tests/integration/__init__.py`**

```bash
touch tests/integration/__init__.py
```

- [ ] **Step 2 : Écrire le test d'intégration (RED)**

```python
# tests/integration/test_api.py
"""Integration test for POST /new_pod_run_model.

The lifespan (Redis connection, worker task) is bypassed with mocks so this
test runs without a real Redis or Docker. It verifies that the HTTP layer
wires together correctly: request deserialization → payload enrichment →
queue push → response serialization.
"""
import base64
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport


@asynccontextmanager
async def mock_lifespan(app):
    """Replace the real lifespan to avoid Redis + worker startup in tests."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.zadd = AsyncMock(return_value=1)
    mock_redis.zremrangebyscore = AsyncMock(return_value=0)
    mock_redis.aclose = AsyncMock()

    mock_queue = AsyncMock()
    mock_queue.push = AsyncMock(return_value=1.5)  # 1.5ms push latency
    mock_queue.close = AsyncMock()

    app.state.redis = mock_redis
    app.state.queue = mock_queue
    yield


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    from app.main import app
    app.router.lifespan_context = mock_lifespan
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestReceiveData:
    @pytest.mark.asyncio
    async def test_returns_queued_status(self, client):
        image_b64 = base64.b64encode(b"fake_image_bytes").decode()
        response = await client.post(
            "/new_pod_run_model",
            json={"image": image_b64, "scenario": "test_scenario"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    @pytest.mark.asyncio
    async def test_returns_correct_scenario(self, client):
        image_b64 = base64.b64encode(b"fake").decode()
        response = await client.post(
            "/new_pod_run_model",
            json={"image": image_b64, "scenario": "my_scenario"},
        )
        assert response.json()["scenario"] == "my_scenario"

    @pytest.mark.asyncio
    async def test_default_scenario(self, client):
        image_b64 = base64.b64encode(b"fake").decode()
        response = await client.post(
            "/new_pod_run_model",
            json={"image": image_b64},
        )
        assert response.status_code == 200
        # Default scenario from config.DEFAULT_SCENARIO
        assert response.json()["scenario"] == "default"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
```

- [ ] **Step 3 : Lancer les tests**

```bash
.venv/bin/pytest tests/integration/test_api.py -v
# Expected: 4 tests PASSED
```

- [ ] **Step 4 : Lancer la suite complète**

```bash
.venv/bin/pytest tests/ -v
# Expected: tous les tests PASSED (17 au total)
```

- [ ] **Step 5 : Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_api.py
git commit -m "test: add integration test for POST /new_pod_run_model"
```

---

## Task 10 : Épingler les dépendances + corriger CLIENT_CALLBACK_URL (P1-3, P1-5)

**Files:**
- Modify: `requirements.txt`
- Modify: `app/config.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1 : Épingler toutes les dépendances**

```bash
# Générer les versions exactes depuis le venv actuel
.venv/bin/pip freeze > requirements.txt
```

Vérifier que le fichier généré contient toujours `pytest`, `pytest-asyncio`, `httpx`. S'ils manquent, les ajouter manuellement avec leur version (`pip show pytest` pour trouver la version).

Vérifier aussi que `flask` et `annotated-doc` n'ont pas été installés dans le venv (s'ils sont présents dans le freeze, les supprimer du `requirements.txt` manuellement car non utilisés).

- [ ] **Step 2 : Corriger `CLIENT_CALLBACK_URL` dans `app/config.py`**

```python
# AVANT (ligne ~25 de config.py) :
CLIENT_CALLBACK_URL: str = os.getenv("CLIENT_CALLBACK_URL", "http://host.docker.internal:5002/save_result")

# APRÈS :
CLIENT_CALLBACK_URL: str = os.getenv("CLIENT_CALLBACK_URL", "")
# Note: host.docker.internal works on macOS Docker Desktop only.
# On Linux, set CLIENT_CALLBACK_URL to the host LAN IP or use host-gateway.
# Leave empty to disable the callback.
```

- [ ] **Step 3 : Corriger `docker-compose.yml`**

Remplacer la valeur hardcodée dans le service `api` :
```yaml
# AVANT :
      - CLIENT_CALLBACK_URL=http://host.docker.internal:5002/save_result

# APRÈS :
      - CLIENT_CALLBACK_URL=${CLIENT_CALLBACK_URL:-}
```

- [ ] **Step 4 : Vérifier que les tests passent toujours**

```bash
.venv/bin/pytest tests/ -v
# Expected: tous PASSED
```

- [ ] **Step 5 : Commit**

```bash
git add requirements.txt app/config.py docker-compose.yml
git commit -m "chore: pin all dependencies and fix CLIENT_CALLBACK_URL portability"
```

---

## Task 11 : Mettre à jour `TODO.md` (P1-4)

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1 : Cocher toutes les tâches Phase 7 dans `TODO.md`**

Remplacer chaque `- [ ]` de la section Phase 7 par `- [x]`.

La section Phase 7 entière doit ressembler à :
```markdown
## Phase 7 : Comparatif Redis vs RabbitMQ ✅

### Abstraction de la couche queue
- [x] Créer `app/queue/base.py` avec une classe abstraite `QueueBackend`
- [x] Extraire la logique Redis dans `app/queue/redis_backend.py`
- [x] Implémenter `app/queue/rabbitmq_backend.py` avec `aio-pika`
- [x] Modifier `app/main.py` et `app/worker.py` pour utiliser `QueueBackend`
- [x] Sélectionner le backend via `QUEUE_BACKEND=redis|rabbitmq`

### Infrastructure
- [x] Ajouter `aio-pika` dans `requirements.txt`
- [x] Ajouter le service `rabbitmq:3-management-alpine` dans `docker-compose.yml`

### Métriques de comparaison
- [x] Ajouter `queue_backend` et `queue_push_latency_ms` dans `InferenceResult`
- [x] Ajouter `make bench-redis` et `make bench-rabbitmq`
- [x] Inclure dans `scripts/plot_results.py` les métriques de comparaison backend
```

- [ ] **Step 2 : Ajouter la section Phase LLM à la fin de `TODO.md`**

```markdown
---

## Phase LLM : InferRouter-LLM (Mémoire)

Extension du routeur pour les grands modèles de langage.

### Objectif
Sélection dynamique de LLMs par estimation sémantique de complexité de prompt
et évaluation automatique de qualité de réponse.

### Modules à créer
- [ ] `app/complexity/estimator.py` — Estimation sémantique de complexité du prompt
- [ ] `app/quality/evaluator.py` — Évaluation automatique de qualité de la réponse LLM
- [ ] Adapter `app/routing/aap.py` → profiler de qualité LLM (remplace IoU par score sémantique)
- [ ] Adapter `app/routing/gpp.py` → intégrer la complexité sémantique dans le calcul de priorité
- [ ] Nouveaux modèles dans `docker-compose.yml` : LLM léger (Ollama / Mistral 7B) + LLM puissant

### Infrastructure
- [ ] Adapter `app/models.py` : `InferenceRequest` avec champ `prompt: str` (au lieu de `image`)
- [ ] Ajouter les clés LLM dans `app/redis_keys.py` : `complexity:...`, `quality:...`
- [ ] Mettre à jour `scripts/plot_results.py` pour les métriques LLM
```

- [ ] **Step 3 : Commit**

```bash
git add TODO.md
git commit -m "docs: sync TODO.md — check Phase 7 complete, add Phase LLM section"
```

---

## Task 12 : Hygiène infrastructure (P2)

**Files:**
- Modify: `docker-compose.yml`
- Rename: `traffic_des_clients/` → `scripts/traffic/`

- [ ] **Step 1 : Ajouter healthchecks et restart policy dans `docker-compose.yml`**

Remplacer le service `api` :
```yaml
  api:
    build: .
    container_name: infer-router-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    depends_on:
      redis:
        condition: service_healthy
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - FAST_MODEL_URL=http://model-fast:5002/new_pod_run_model
      - ACCURATE_MODEL_URL=http://model-accurate:5002/new_pod_run_model
      - CLIENT_CALLBACK_URL=${CLIENT_CALLBACK_URL:-}
      - ROUTING_STRATEGY=${ROUTING_STRATEGY:-infer-router}
      - QUEUE_BACKEND=${QUEUE_BACKEND:-redis}
      - RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
    networks:
      - infer-net
    volumes:
      - .:/app
```

Ajouter un healthcheck au service `redis` :
```yaml
  redis:
    image: redis:8.4.1-trixie
    container_name: infer-router-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    networks:
      - infer-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
```

- [ ] **Step 2 : Renommer `traffic_des_clients/` → `scripts/traffic/`**

```bash
mkdir -p scripts/traffic
cp traffic_des_clients/user_request.py scripts/traffic/user_request.py
git rm -r traffic_des_clients/
git add scripts/traffic/user_request.py
```

Vérifier que `traffic_des_clients/` n'est référencé nulle part dans le code (Makefile, README) — si oui, mettre à jour les références.

```bash
grep -r "traffic_des_clients" --include="*.py" --include="Makefile" --include="*.md" .
# Mettre à jour chaque occurrence trouvée
```

- [ ] **Step 3 : Vérifier que les tests passent**

```bash
.venv/bin/pytest tests/ -v
# Expected: tous PASSED
```

- [ ] **Step 4 : Commit final**

```bash
git add docker-compose.yml scripts/traffic/
git commit -m "chore: add healthchecks, restart policy, rename traffic_des_clients to scripts/traffic"
```

---

## Vérification finale

- [ ] `make run` démarre sans erreur
- [ ] `.venv/bin/pytest tests/ -v` — tous les tests PASSED
- [ ] `docker build -t infer-router-test .` — image buildée (vérifier la taille avec `docker images infer-router-test`)
- [ ] `cat .env.example` — toutes les variables env documentées
- [ ] `TODO.md` — Phase 7 cochée, section Phase LLM présente

---

## Self-Review

**Couverture du spec :**

| Tâche spec | Task plan |
|------------|-----------|
| P0-1 request_builder | Task 3 |
| P0-2 result_store | Task 4 |
| P0-3 redis_keys | Task 1 |
| P0-4 config constants | Task 2 |
| P0-5 .env.example | Task 5 |
| P0-6 .dockerignore | Task 5 |
| P1-1 tests unitaires | Tasks 6, 7, 8 |
| P1-2 test intégration | Task 9 |
| P1-3 pin deps | Task 10 |
| P1-4 TODO.md | Task 11 |
| P1-5 CLIENT_CALLBACK_URL | Task 10 |
| P2-1 renommer traffic_des_clients | Task 12 |
| P2-2 healthchecks | Task 12 |
| P2-3 restart policy | Task 12 |
| P2-4 supprimer flask | Task 10 (pip freeze + nettoyage manuel) |
| P2-5 vérifier annotated-doc | Task 10 (pip freeze + nettoyage manuel) |

Toutes les exigences du spec sont couvertes.
