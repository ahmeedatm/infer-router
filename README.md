# Infer Router

Ce dépôt contient une API FastAPI nommée "Infer Router" qui route des demandes d'inférence vers des modèles simulés en fonction de la charge de la file d'attente (Redis). Le but principal est de démontrer une logique de routage adaptative (privilégier latence vs précision) selon la taille de la file.

**Structure du projet**

- app/
  - main.py : implémentation principale de l'API FastAPI, gestion du cycle de vie et du worker d'inférence.
- docker-compose.yml : (optionnel) composition pour lancer l'API et Redis.
- Dockerfile : image de l'application.
- requirements.txt : dépendances Python.

**Résumé des fonctionnalités implémentées**

- **Serveur HTTP**: API FastAPI exposant des endpoints REST.
- **Queue Redis (asyncio)**: les requêtes d'inférence sont poussées dans la liste Redis `inference_queue`.
- **Worker asynchrone**: une tâche de fond lit la file avec `BRPOP` et exécute une inférence simulée.
- **Routage adaptatif**: si la longueur de la file dépasse un seuil (`QUEUE_THRESHOLD = 5`), le worker choisit un modèle rapide (`Fast-Model`) pour privilégier la latence ; sinon il choisit un modèle précis (`Accurate-Model`).
- **Historique des résultats**: chaque inférence aboutie est poussée dans `inference_results` (liste Redis) avec métadonnées (id du capteur, modèle utilisé, latence, longueur de file au départ).
- **Lifespan FastAPI**: création et fermeture du client Redis et lancement/arrêt propre du worker via un `asynccontextmanager`.

**Fichiers clés et explication**

- `app/main.py` :
  - Import des bibliothèques (`FastAPI`, `uvicorn`, `pydantic`, `redis.asyncio`, `asyncio`, etc.).
  - Définition du modèle Pydantic `InferenceRequest` avec `sensor_id`, `timestamp` et `features`.
  - Fonction `process_inference(redis_client)` : boucle infinie qui lit `inference_queue`, calcule la longueur de la file, choisit `Fast-Model` ou `Accurate-Model`, simule un temps de calcul (`0.5s` ou `2.0s`), calcule la latence et stocke l'historique dans `inference_results`.
  - `lifespan(app)` : initialise `app.state.redis = Redis(host="redis", port=6379)`, lance `process_inference` en tâche de fond et effectue le nettoyage (annulation de la tâche et fermeture du client Redis).
  - Endpoints :
    - `GET /` : message de bienvenue.
    - `GET /health` : état `ok`.
    - `GET /results` : retourne les 10 derniers résultats depuis `inference_results`.
    - `POST /data` : reçoit `InferenceRequest`, sérialise en JSON et fait `LPUSH inference_queue`.

**Comment l'exécuter localement**

Méthode 1 — avec `uvicorn` (environnement virtuel activé) :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Méthode 2 — avec Docker / docker-compose (si `docker-compose.yml` fourni) :

```bash
docker-compose up --build
```

(Remarque : le service Redis doit être joignable à l'hôte `redis` sur le port `6379` si vous utilisez la configuration par défaut du projet.)

**Exemples d'usage (tests rapides)**

1) Poster une donnée d'inférence :

```bash
curl -X POST "http://localhost:8000/data" -H "Content-Type: application/json" -d '
{
  "sensor_id": "sensor-01",
  "timestamp": 1670000000.0,
  "features": [0.1, 0.2, 0.3]
}'
```

2) Récupérer les derniers résultats :

```bash
curl http://localhost:8000/results
```

3) Simulation rapide pour déclencher le mode dégradé : envoyer plusieurs requêtes POST en parallèle (ou utiliser un petit script loop) pour augmenter la longueur de la file au-dessus du seuil `5`.

**Lancer les tests**

Le `make test` intégré démarre l'API, vide Redis, envoie des requêtes et attend le traitement :

```bash
# Test basique (10 requêtes, seuil 5)
make test

# Paramétré
make test N=20 THRESHOLD=3

# Multi-scénarios
python3 scripts/send_requests.py --count 20 --scenario adaptive
python3 scripts/send_requests.py --count 20 --scenario always-fast

# Vérifier les résultats par scénario
curl "http://localhost:8000/scenarios"
curl "http://localhost:8000/results?scenario=adaptive"

# Dashboard live (se rafraîchit toutes les 10 s)
open http://localhost:8000/dashboard

# Résilience : injecter un message malformé (le worker doit continuer)
docker exec infer-router-redis redis-cli LPUSH inference_queue "bad-json"
curl http://localhost:8000/health   # doit retourner {"status":"ok"}
```

**Dépendances importantes**

- fastapi
- uvicorn
- redis (version 4.x+ avec support `redis.asyncio`)
- pydantic

Ces dépendances doivent être listées dans `requirements.txt`.

**Remarques d'implémentation & limites**

- Les modèles (`Fast-Model`, `Accurate-Model`) sont simulés par des `asyncio.sleep`. Il faut remplacer cette simulation par des appels réels d'inférence (HTTP RPC, gRPC, chargement local de modèle) pour un usage en production.
- L'utilisation actuelle de `BRPOP` bloque jusqu'à réception : c'est volontaire pour la logique du worker. En production, on peut envisager un timeout, gestion d'exceptions réseau et backoff.
- La métrique `latency` est calculée comme `time.time() - timestamp` envoyé par le client. Veillez à synchroniser les horloges (NT P) si la latence est critique.
- Gestion des erreurs et des cas limites (messages malformés, Redis down) doit être renforcée (retries, dead-letter queue, logs structurés).

**Améliorations possibles**

- Ajouter des tests unitaires et d'intégration.
- Exposer des métriques Prometheus (latences, longueur de file, modèle sélectionné).
- Remplacer la simulation des modèles par une intégration réelle (TensorFlow/PyTorch, ou requêtes vers des microservices d'inférence).
- Paramétrer `QUEUE_THRESHOLD` via variable d'environnement ou configuration.
- Ajouter authentification/autorisation pour l'API si nécessaire.

**To-Do List consolidée (version académique)**

Voici la To-Do List consolidée de ton projet InferRouter. Elle est structurée pour coller parfaitement à ton sujet académique.

✅ **Phase 1 : Infrastructure & Mécanique de base (Terminé)**
Tout ce qui concerne la "plomberie" du système est opérationnel.

- [x] Mise en place Docker : Conteneurs API et Redis qui communiquent dans un réseau isolé (`docker-compose`).
- [x] API d'Ingestion : Route `POST /data` qui reçoit les données JSON et valide le format (Pydantic).
- [x] Système de File d'Attente : Sérialisation des requêtes et stockage dans une liste Redis (`LPUSH`).
- [x] Worker Asynchrone : Tâche de fond qui dépile les messages (`BRPOP`) sans bloquer l'API.
- [x] Simulation des Modèles : Utilisation de `asyncio.sleep()` pour simuler des temps de calcul différents (Fast vs Accurate).

✅ **Phase 2 : Métriques & Première Intelligence (Terminé)**
Le système est capable de s'observer et de réagir à la charge.

- [x] Calcul de Latence : Mesure du temps total ($T_{fin} - T_{début}$) pour chaque requête.
- [x] Historisation : Sauvegarde des résultats (latence, modèle utilisé) dans Redis (`inference_results`).
- [x] Visualisation : Route `GET /results` pour consulter l'historique depuis Postman.
- [x] Contrôle par Seuil (Charge) : Le Worker vérifie la taille de la file (`LLEN`). Si file ≥ 5, il bascule automatiquement sur le modèle rapide.

✅ **Phase 2.5 : Refactoring, Corrections de Bugs & Scénarios (Terminé)**
Architecture modulaire, trois bugs corrigés, et support multi-scénarios avec dashboard live.

- [x] Refactoring modulaire : Code découpé en `config.py`, `models.py`, `worker.py`, `dashboard.py` — `main.py` réduit aux routes uniquement (~70 lignes).
- [x] Bug fix — Off-by-one : Correction du seuil (`>` → `>=`) pour que `Fast-Model` se déclenche au bon moment.
- [x] Bug fix — JSON malformé : Le worker attrape les `json.JSONDecodeError` et continue sans planter.
- [x] Bug fix — Liste Redis non bornée : `LPUSH` + `LTRIM` atomique (pipeline) pour plafonner chaque liste à 1000 entrées.
- [x] Tagging par scénario : Le champ `scenario` (optionnel, défaut `"default"`) est propagé de `POST /data` jusqu'aux résultats Redis (`inference_results:{scenario}`).
- [x] Route `GET /scenarios` : Liste tous les scénarios présents dans Redis.
- [x] Route `GET /results?scenario=` : Filtre les résultats par scénario.
- [x] Dashboard live `GET /dashboard` : Page HTML avec Chart.js (courbe de latence + donut de distribution par modèle), auto-refresh toutes les 10 s.
- [x] Script `--scenario` : `scripts/send_requests.py` accepte `--scenario` et l'inclut dans le corps POST.

📝 **Phase 3 : Profilage Dynamique & Feedback (À FAIRE)**
C'est l'étape actuelle. Le système doit apprendre de ses erreurs (Rétroaction).

- [x] Gestion de l'état des modèles : Stocker la précision actuelle de chaque modèle dans Redis (ex: `accuracy:Fast-Model = 0.60`).
- [x] Route de Feedback : Créer une route `POST /feedback` permettant à un utilisateur (ou simulateur) de dire "La précision de ce modèle a baissé".
- [x] Intégration dans le Worker : Le Worker doit récupérer la précision actuelle du modèle choisi au moment du calcul pour l'enregistrer dans l'historique.

📝 **Phase 4 : Stratégie de Priorisation (À FAIRE)**
Le "Cerveau" final. Il doit prendre une décision basée sur DEUX critères : la file d'attente ET la précision.

- [x] Algorithme de décision : Implémenter une logique un peu plus fine.

  Exemple : "Si la file est vide MAIS que le modèle précis est devenu mauvais (feedback < 0.5), alors utiliser le modèle rapide quand même."
- [x] Mode Dégradé : S'assurer que le système ne plante pas si les précisions ne sont pas définies.

📝 **Phase 5 : Comparaison & Rapport (À FAIRE)**
La preuve scientifique pour ton rendu.

- [ ] Scénario "Témoin 1" : Faire un test en forçant le système à utiliser toujours le modèle `Accurate` (et voir la latence exploser).
- [ ] Scénario "Témoin 2" : Faire un test avec toujours le modèle `Fast` (latence basse, mais précision faible).
- [ ] Scénario "InferRouter" : Faire le test avec ton algorithme (latence maîtrisée + précision optimisée).
- [ ] Export des données : Récupérer le JSON de `/results` pour en faire un graphique (Excel ou Python/Matplotlib) comparant les 3 courbes.