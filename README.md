# InferRouter-LLM

Routage dynamique d'intents réseau en langage naturel vers un pool de LLM
spécialisés, par estimation de complexité sémantique et évaluation automatique
de qualité.

Un intent réseau (par exemple « créer une slice URLLC à faible latence pour
véhicules connectés ») est analysé, puis dirigé vers le modèle de langage le
mieux adapté sous contraintes de qualité, de latence et de coût. La qualité des
réponses est évaluée par un LLM-Juge exécuté localement.

## Principe

```
        Intent réseau (langage naturel)
                    │
                    ▼
        Estimateur de complexité ──► (n entités, profondeur, domaines croisés)
                    │
                    ▼
        Routeur tri-critère ──► admissibilité (latence, coût) + argmax qualité
                    │
        ┌───────────┼────────────┐
        ▼           ▼            ▼
   LLM générique   LLM spécialisés par domaine
   (fallback)      (RAN, cœur, sécurité, slice)
                    │
                    ▼
        LLM-Juge local (RocketEval, Ollama) ──► qualité estimée
```

Trois composants :

1. **Estimateur de complexité** : un classifieur léger prédit le niveau de
   complexité d'un intent (simple, medium, complex) à partir d'attributs
   calculés sur l'énoncé (nombre d'entités, profondeur d'inférence, domaines
   croisés). Moins de 15 ms par intent.
2. **Routeur tri-critère** : sélectionne le modèle admissible de plus haute
   qualité attendue, les égalités étant tranchées par le coût puis la latence.
3. **LLM-Juge local** : évalue la qualité d'une réponse par la méthode
   RocketEval (checklist générée par intent, notée par un petit modèle local via
   Ollama), sans dépendre d'un service externe payant au runtime.

## Structure du dépôt

```
app/llm/
  schema.py             modèles de données (Intent, ModelResponse, JudgeScore...)
  intents.py            chargement et validation du jeu d'intents
  features.py           extraction d'attributs de complexité
  openrouter_client.py  appel des LLM cibles (OpenRouter)
  judge.py              LLM-Juge (RocketEval, scores et notation par paires)
  checklist.py          génération de checklist d'évaluation par intent
  pool.py               pool de modèles (génériques et spécialisés)
  policy.py             qualité attendue par candidat
  inferrouter.py        orchestrateur de routage
  router.py             logique de sélection (admissibilité, argmax, départage)

data/
  intents_dataset.yaml  jeu d'intents annoté (domaine, complexité, criticité)

experiments/            campagnes d'évaluation (calibration, benchmark, juge)
scripts/                génération du dataset, utilitaires
tests/                  tests unitaires et d'intégration
```

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Configuration par variables d'environnement (voir `.env.example`) :

- `OPENROUTER_API_KEY` : clé pour appeler les LLM cibles.
- `MODEL_LIGHT`, `MODEL_HEAVY` : modèles du pool.
- `OLLAMA_HOST`, `JUDGE_MODEL` : juge local (Ollama).

Le juge local requiert [Ollama](https://ollama.com/) et un modèle, par exemple :

```bash
ollama pull gemma2:9b
```

## Utilisation

```python
from app.llm.schema import Intent
from app.llm.inferrouter import route

intent = Intent(
    id="ex1",
    text="Create a low-latency URLLC slice for connected vehicles.",
    domain="slice",
    expected_complexity="complex",
    criticality="high",
)

decision = route(intent, l_max=5000, c_max=1.0)
print(decision.model_id, decision.rationale)
```

## Tests

```bash
.venv/bin/pytest tests/unit -q     # tests unitaires (sans réseau ni service)
.venv/bin/ruff check .             # lint
```

Les tests d'intégration (`tests/integration/`) requièrent Ollama et ne sont pas
exécutés par défaut.

## Évaluation

Le dossier `experiments/` contient les campagnes de mesure : fiabilité du juge,
séparabilité de la complexité, calibration de la qualité par modèle, et
comparaison des stratégies de routage. Ces scripts appellent des API payantes ;
ils valident sur de petits échantillons avant tout passage à l'échelle et
réutilisent les artefacts déjà produits.
