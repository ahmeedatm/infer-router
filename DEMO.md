# InferRouter — Scénario de démonstration vidéo

## Avant de commencer

```bash
# 1. Démarrer la stack
make up

# 2. Vérifier que les 4 conteneurs sont verts
docker compose ps

# 3. Nettoyer Redis pour un état propre
docker exec infer-router-redis redis-cli FLUSHALL
```

**Disposition de l'écran :**

| Pane gauche | Pane centre | Pane droite |
|-------------|-------------|-------------|
| Logs live | Tes commandes | Résultats live |

```bash
# Pane gauche — logs filtrés
docker compose logs -f api 2>&1 | grep -E "(INFO|WARNING|ERROR)"

# Pane droite — résultats auto-refresh
watch -n 3 'curl -s "http://localhost:8000/results?scenario=demo_burst" | python3 -m json.tool 2>/dev/null | head -40'
```

**Navigateur — ouvrir avant d'enregistrer :**
- `http://localhost:8000/dashboard`
- `http://localhost:8000/config`

---

## Scène 1 — Démarrage & santé (30s)

**Objectif :** Montrer que la stack tourne correctement.

```bash
docker compose ps
curl http://localhost:8000/health
```

**Ce qu'on voit :** 4 conteneurs `Up`, réponse `{"status": "ok"}`.

**À dire :** *"InferRouter démarre 4 conteneurs Docker : l'API FastAPI, Redis, et deux modèles YOLO — un rapide (tiny) et un précis (large)."*

---

## Scène 2 — Configuration live (30s)

**Objectif :** Expliquer les paramètres de l'algorithme.

```bash
curl http://localhost:8000/config | python3 -m json.tool
```

**Pointer avec le curseur :**
- `routing_strategy: "infer-router"` → algorithme adaptatif actif
- `tau: 5.0` → budget SLA en secondes
- `k_active` → nombre de modèles actifs (1 ou 2)
- `lambda_current` → taux d'arrivée mesuré (req/s)
- `mu` → débit de service par modèle (req/s)

**À dire :** *"L'algorithme mesure en temps réel λ (arrivées) et μ (service). Le paramètre τ est le budget de latence SLA. Si le temps d'attente estimé w(k) dépasse τ, un deuxième modèle est activé."*

---

## Scène 3 — Requête unique (45s)

**Objectif :** Montrer le cycle complet d'une requête.

```bash
IMAGE=$(base64 -i data/images/000000000009.jpg)

curl -s -X POST http://localhost:8000/new_pod_run_model \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"$IMAGE\", \"scenario\": \"demo\"}"
```

Attendre ~3 secondes, puis :

```bash
curl -s "http://localhost:8000/results?scenario=demo" | python3 -m json.tool
```

**Pointer dans le résultat :**
- `model` → quel modèle a traité la requête
- `routing_reason: "infer_k1_gold"` → file faible, modèle précis choisi
- `k_active: 1` → un seul modèle actif
- `latency` → temps de traitement en secondes

**À dire :** *"Avec une file vide, w(k=1) est bien inférieur à τ. Le routeur choisit le modèle précis — c'est la décision 'infer_k1_gold'."*

---

## Scène 4 — Dashboard live (20s)

**Objectif :** Montrer la visualisation temps réel.

Basculer sur le navigateur → onglet `http://localhost:8000/dashboard`.

**À dire :** *"Le dashboard se rafraîchit toutes les 10 secondes. On voit les décisions de routage, les métriques λ/μ, et la précision des modèles en temps réel."*

---

## Scène 5 — Burst de trafic ← SCÈNE CLÉ (90s)

**Objectif :** Démontrer l'adaptation dynamique du routeur sous charge.

> Rendre les 3 panes visibles simultanément avant de lancer.

```bash
python3 scripts/traffic_client.py --count 30 --rate 0.1 --scenario demo_burst
```

**Ce qu'on observe en temps réel :**

| Pane gauche (logs) | Pane droite (résultats) |
|--------------------|------------------------|
| `routing_reason` passe de `infer_k1_gold` à `infer_k2_fast` | Nouveaux résultats apparaissent toutes les 3s |
| `k=1 → k=2` dans les logs | `model` alterne entre Fast et Accurate |

**À dire :** *"On envoie 30 requêtes à 0.1s d'intervalle, soit ~10 req/s. Le contrôleur détecte que w(k=1) dépasse τ=5s et active le deuxième modèle. Les décisions passent de 'infer_k1_gold' à 'infer_k2_fast' — l'algorithme bascule dynamiquement."*

---

## Scène 6 — Comparaison des stratégies (60s)

**Objectif :** Montrer la différence entre les 3 modes de routage.

```bash
# Passer en always-fast
ROUTING_STRATEGY=always-fast docker compose up -d --no-deps api
sleep 4

python3 scripts/traffic_client.py --count 10 --rate 0.5 --scenario demo_fast

curl -s "http://localhost:8000/results?scenario=demo_fast" | python3 -m json.tool
```

**Pointer :** `routing_reason: "static_fast"` → toujours le modèle rapide, pas de logique adaptative.

```bash
# Revenir à infer-router
ROUTING_STRATEGY=infer-router docker compose up -d --no-deps api
```

**À dire :** *"En mode always-fast, latence minimale garantie mais sans adaptation. En mode always-accurate, précision maximale mais la latence explose sous charge. InferRouter choisit dynamiquement selon l'état du système."*

---

## Scène 7 — Résultats du benchmark (45s)

**Objectif :** Présenter les données comparatives pré-générées.

```bash
ls data/bench/
```

Ouvrir le graphe le plus parlant :

```bash
open data/plots/latency_comparison.png
```

**Commenter :** always-fast ~0.2s, always-accurate ~1.1s, infer-router adaptatif.

Puis montrer le graphe clé :

```bash
open data/plots/infer_router_timeseries_mixed.png
```

**À dire :** *"C'est le graphe le plus important. En charge mixte, k_active passe proprement de 1 à 2 pendant le burst, puis revient à 1 quand la charge retombe. λ monte à 8.5 req/s pendant le pic — le système l'absorbe sans dépasser le budget SLA."*

---

## Scène 8 — Rapport auto-généré (20s)

**Objectif :** Montrer la génération automatique du rapport d'analyse.

```bash
make report
head -80 REPORT.md
```

**À dire :** *"Le rapport est généré automatiquement à partir des données de benchmark — tableaux de latence, précision, débit, et analyse comparative Redis vs RabbitMQ."*

---

## Reset entre deux prises

```bash
docker exec infer-router-redis redis-cli FLUSHALL
ROUTING_STRATEGY=infer-router docker compose up -d --no-deps api
sleep 3
```

---

## Récapitulatif des décisions de routage

| `routing_reason` | Signification |
|-----------------|---------------|
| `infer_k1_gold` | k=1, file faible → modèle précis choisi |
| `infer_k2_accurate` | k=2, GPP préfère quand même le modèle précis |
| `infer_k2_fast` | k=2, file chargée → modèle rapide choisi par GPP |
| `static_fast` | Stratégie always-fast |
| `static_accurate` | Stratégie always-accurate |

## Durée cible par scène

| Scène | Durée |
|-------|-------|
| 1 — Démarrage | 30s |
| 2 — Configuration | 30s |
| 3 — Requête unique | 45s |
| 4 — Dashboard | 20s |
| 5 — Burst de trafic | 90s |
| 6 — Comparaison stratégies | 60s |
| 7 — Benchmark & plots | 45s |
| 8 — Rapport | 20s |
| **Total** | **~6 min** |
