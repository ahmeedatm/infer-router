# TODO — Phases restantes

## Phase 1 : Intégration des vrais modèles IA (Docker Hub) ✅

Remplacer les `sleep()` simulés par de vrais appels HTTP vers les microservices IA fournis par le tuteur sur Docker Hub. L'infer-router se place en proxy entre le client de trafic et les containers modèles.

```
scripts/traffic/user_request.py
        │  POST /new_pod_run_model  {"image": "<base64>"}
        ▼
   infer-router  (routage selon charge + précision)
        │
   ┌────┴────┐
   ▼         ▼
pntumba/     pntumba/
model_variant_tiny   model_variant_large
(Fast-Model)         (Accurate-Model)
```

- [x] Remplacer `POST /data` par `POST /new_pod_run_model`
- [x] Adapter `InferenceRequest` : `image: str` (base64) + `scenario`
- [x] Générer `sensor_id`, `timestamp`, `image_size` côté routeur
- [x] Ajouter les containers modèles dans `docker-compose.yml`
- [x] Créer `app/inference.py` : `call_model(model_url, image_b64)` via httpx
- [x] Modifier `app/worker.py` pour appeler `call_model()` au lieu de `asyncio.sleep()`
- [x] Afficher `image_size` et accuracy réelle sur le dashboard

---

## Phase 2 : Stratégies de routage statiques (prérequis benchmark) ✅

Ajouter la possibilité de basculer entre les trois modes de routage via une variable d'env.
Nécessaire pour comparer InferRouter contre les baselines dans la Phase 5 (benchmark).

- [x] Ajouter `ROUTING_STRATEGY` dans `app/config.py` (`infer-router` | `always-fast` | `always-accurate`)
- [x] Implémenter les deux stratégies statiques dans `app/worker.py` :
  - `always-fast` : toujours Fast-Model, indépendamment de la file
  - `always-accurate` : toujours Accurate-Model, indépendamment de la file
  - `infer-router` : algorithme dynamique (Phases 3 et 4)
- [x] Exposer `ROUTING_STRATEGY` courante dans `GET /config`

---

## Phase 3 : Mesure des paramètres système (λ et μ) ✅

Prérequis pour les formules de l'article. Toutes les décisions de routage dynamique
(Phase 4) dépendent de λ (taux d'arrivée) et μ (taux de service de chaque modèle).

### 3a — Taux d'arrivée λ (req/s)

- [x] Créer `app/arrival.py` : compteur de requêtes avec fenêtre glissante de 5s
  - Incrémenter à chaque `LPUSH` dans `POST /new_pod_run_model`
  - Stocker la valeur dans Redis : `metrics:lambda` (mis à jour toutes les secondes)
- [x] Exposer `lambda_current` dans `GET /config`

### 3b — Taux de service μ par modèle (req/s)

- [x] Mesurer μ à partir des latences réelles stockées dans Redis :
  - `mu = 1 / mean(latency)` calculé sur les N derniers résultats de chaque modèle
  - Stocker dans Redis : `metrics:mu:Fast-Model` et `metrics:mu:Accurate-Model`
- [x] Vérifier la condition de stabilité du papier : `sum(μᵢ) > λ` — logguer un warning sinon
- [x] Exposer `mu` par modèle dans `GET /config`

---

## Phase 4 : Algorithme InferRouter (AAP + GPP + Threshold Control) ✅

Implémentation des trois modules décrits dans le papier IEEE.
**Remplace** l'ancien `_select_model()` binaire, `POST /feedback` manuel, et `PUT /threshold` manuel.

> Référence : Section IV de l'article — "InferRouter Design"

### 4a — Anti-Idling Accuracy Profiling (AAP)

> Section IV-A — le module qui auto-calibre l'accuracy sans surcharge

- [x] Créer `app/aap.py` :
  - Quand le modèle gold-standard (Accurate-Model) traite une requête, envoyer simultanément
    la même requête à tout modèle **idle** dont `μⱼ ≥ λ`
  - Comparer le résultat retourné par le modèle idle au résultat gold-standard
  - Maintenir un sliding window de `l = 10` comparaisons récentes par modèle (configurable via `AAP_WINDOW`)
  - Mettre à jour l'accuracy dans Redis : `accuracy:<model>` = ratio de sorties cohérentes
- [x] Supprimer `POST /feedback` dans `app/main.py` (accuracy désormais auto-profilée)
- [x] Supprimer `FeedbackRequest` et `FeedbackResponse` dans `app/models.py`
- [x] Ajouter `AAP_WINDOW = 10` dans `app/config.py`

### 4b — Gold-Pair Prioritizing (GPP)

> Section IV-B — formule de priorité `p(i) = αᵢ + ω(μ*) · c / μᵢ`

- [x] Créer `app/gpp.py` :
  - Définir le modèle gold-standard `f* = Accurate-Model` (α* = 0 par convention)
  - Implémenter `compute_priority(alpha_i, mu_i, mu_star, c, omega) -> float`
    - `p(i) = alpha_i + omega * c / mu_i`  (valeur basse = priorité haute)
    - `omega` est calibré depuis un unique point DP optimal (offline) — initialiser à 1.0,
      peut être affiné via `POST /calibrate`
  - Retourner les modèles triés par priorité croissante
- [x] Ajouter `C_COEFFICIENT = 1.0` et `OMEGA = 1.0` dans `app/config.py`
- [x] Supprimer `ACCURACY_PENALTY_THRESHOLD` dans `app/config.py` (remplacé par GPP)

### 4c — Waiting-Based Threshold Control

> Section IV-C — machine à trois états : scale-up / maintien / scale-down

- [x] Créer `app/threshold.py` :
  - Implémenter `compute_waiting_time(k, queue_length, mu_k, lambda_, tau) -> float` :
    ```
    w(k) = (x - 1) / (2 * mu[k])  +  tau / (1 + exp(mu[k] - lambda_))
    ```
    où `mu[k]` = moyenne des taux de service des k modèles actifs
  - Implémenter la machine à trois états à chaque nouvelle requête :
    - `w(k-1) ≤ τ` → scale-down (retirer un modèle, utiliser k-1)
    - `w(k) > τ`   → scale-up (ajouter un modèle, utiliser k+1)
    - sinon        → maintien (garder k modèles actifs)
  - Stocker `k_active` dans Redis : `metrics:k_active`
- [x] Ajouter `TAU = 5.0` dans `app/config.py` (budget de temps d'attente max, en secondes)
- [x] Supprimer `QUEUE_THRESHOLD` fixe et `THRESHOLD_REDIS_KEY` dans `app/config.py`
- [x] Supprimer `PUT /threshold` dans `app/main.py`
- [x] Supprimer `ThresholdUpdateRequest` et `ThresholdUpdateResponse` dans `app/models.py`

### 4d — Intégration dans le worker

- [x] Modifier `app/worker.py` :
  - Remplacer `_select_model()` par l'appel séquentiel : `threshold.py` → `gpp.py` → dispatch
  - Après inference gold-standard : déclencher `aap.py` en parallèle (`asyncio.create_task`)
  - Logguer `k_active`, `lambda_`, `mu` et `routing_reason` à chaque requête
- [x] Mettre à jour `GET /config` pour exposer `tau`, `c`, `omega`, `lambda_current`, `k_active`, `mu` par modèle
- [x] Mettre à jour `GET /accuracy` pour exposer aussi la priorité `p(i)` par modèle
- [x] Mettre à jour le dashboard : afficher `k actifs`, `λ`, `τ`, `seuil calculé w(k)` en temps réel

---

## Phase 5 : Campagne de benchmark ✅

Comparer les trois stratégies (`always-fast`, `always-accurate`, `infer-router`) sur des scénarios
de charge progressive. Reproduit la méthodologie du papier (Table IV).

### Métriques cibles (conformes au papier)

- **P99 latency** — métrique primaire du papier (tail latency)
- **Latence moyenne**
- **Accuracy moyenne** (cohérence avec gold-standard)
- Débit effectif (req/s traités)

### Scénarios de charge

- [x] Charge normale : N=100 req, rate=0.5 req/s
- [x] Burst de charge : N=50 req, rate=10 req/s (pic 20× — reproduit le protocole HAR du papier)
- [x] Charge mixte : 200 req normales + 100 req burst (séquence 1–200 normal, 201–300 burst, 301–500 normal)

### Automatisation

- [x] Ajouter `GET /export?scenario=X` retournant **tous** les résultats du scénario (pas seulement les 10 derniers)
- [x] Créer `scripts/plot_results.py` générant les graphiques à partir des JSON exportés :
  - Latence moyenne, P95, P99 par stratégie
  - Accuracy moyenne par stratégie
  - Courbes en fonction de la charge (débit vs latence)
  - Évolution de `k_active` et `λ` en fonction du temps (infer-router uniquement)
- [x] Automatiser dans le `Makefile` :
  - `make bench` : lance les 3 stratégies × 3 scénarios de charge, flush Redis entre chaque run
  - `make plot` : génère les graphiques depuis les JSON exportés

---


## Phase 7 : Comparatif Redis vs RabbitMQ ✅

Abstraire la couche queue derrière une interface interchangeable et benchmarker les deux backends.

### Abstraction de la couche queue

- [x] Créer `app/queue/base.py` avec une classe abstraite `QueueBackend` : `push()`, `pop()`, `length()`, `close()`
- [x] Extraire la logique Redis dans `app/queue/redis_backend.py`
- [x] Implémenter `app/queue/rabbitmq_backend.py` avec `aio-pika`
- [x] Modifier `app/main.py` et `app/worker.py` pour utiliser `QueueBackend`
- [x] Sélectionner le backend via `QUEUE_BACKEND=redis|rabbitmq` dans `app/config.py`

### Infrastructure

- [x] Ajouter `aio-pika` dans `requirements.txt`
- [x] Ajouter le service `rabbitmq:3-management-alpine` dans `docker-compose.yml` (ports 5672 / 15672)

### Métriques de comparaison

- [x] Ajouter `queue_backend` et `queue_push_latency_ms` dans `InferenceResult`
- [x] Ajouter `make bench-redis` et `make bench-rabbitmq` (scénario N=100 identique pour les deux)
- [x] Inclure dans `scripts/plot_results.py` : latence P50/P95/P99 et throughput par backend

---

## Phase 8 : Rapport final

- [ ] Rédiger l'analyse des résultats du benchmark (Phase 5)
- [ ] Comparer les résultats obtenus aux valeurs du papier (Table IV — P99 latency, accuracy)
- [ ] Conclure sur les conditions dans lesquelles InferRouter est supérieur aux stratégies statiques
- [ ] Documenter l'impact de τ (budget de temps d'attente) sur le compromis précision/latence
- [ ] Conclure sur le choix de Redis vs RabbitMQ pour ce cas d'usage (Phase 7)
- [ ] Mettre à jour la présentation avec les graphiques générés

---

## Phase LLM : InferRouter-LLM (Mémoire)

Extension du routeur pour les grands modèles de langage.

### Objectif
Sélection dynamique de LLMs par estimation sémantique de complexité de prompt
et évaluation automatique de qualité de réponse.

### Modules à créer
- [ ] `app/complexity/estimator.py` — Estimation sémantique de complexité du prompt
- [ ] `app/quality/evaluator.py` — Évaluation automatique de qualité de la réponse LLM
- [ ] Adapter `app/aap.py` → profiler de qualité LLM (remplace IoU par score sémantique)
- [ ] Adapter `app/gpp.py` → intégrer la complexité sémantique dans le calcul de priorité
- [ ] Nouveaux modèles dans `docker-compose.yml` : LLM léger + LLM puissant (Ollama-compatible)

### Infrastructure
- [ ] Adapter `app/models.py` : `InferenceRequest` avec champ `prompt: str` (au lieu de `image`)
- [ ] Ajouter les clés LLM dans `app/redis_keys.py` : `complexity:...`, `quality:...`
- [ ] Mettre à jour `scripts/plot_results.py` pour les métriques LLM
