# Design — Sélection des modèles LLM pour InferRouter-LLM

**Date :** 2026-05-06
**Projet :** InferRouter-LLM (Mémoire Master MR11606C — CNAM)
**Soutenance :** Septembre 2026

---

## Contexte

InferRouter-LLM étend le routeur bi-critère original (vision) vers les grands modèles de langage.
Le système route chaque requête texte vers l'un des trois tiers LLM en fonction d'un score de
complexité sémantique estimé localement.

Contraintes déterminantes :
- Pas de GPU local (MacBook Air M5, 24GB RAM)
- Budget étudiant : free tiers uniquement
- Latence Complexity Estimator : **< 50ms** (non-négociable)
- Une seule clé API (lisibilité du code, surface de panne minimale)
- Résultats benchmarkables et reproductibles pour le jury

---

## Stack retenue

| Rôle | Modèle | Provider | Latence estimée | Quota |
|---|---|---|---|---|
| **Complexity Estimator** | `all-MiniLM-L6-v2` + classifier | Local M5 (sentence-transformers) | 5–15ms | ∞ |
| **Tier léger** | `google/gemma-3-4b-it:free` | OpenRouter | ~1–2s | 200 req/day |
| **Tier équilibré** | `google/gemma-3-12b-it:free` | OpenRouter | ~2–3s | 200 req/day |
| **Tier lourd** | `google/gemma-3-27b-it:free` | OpenRouter | ~2–4s | 200 req/day |
| **LLM Juge** | `gemma2:2b` (Ollama) | Local M5 | ~200ms | ∞ |

---

## Architecture du flux

```
Requête utilisateur
      │
      ▼
┌─────────────────────────────────┐
│  Complexity Estimator (LOCAL)   │  < 50ms
│  all-MiniLM-L6-v2 + classifier  │
│  Cache cosine similarity ≥ 0.92 │
└────────────┬────────────────────┘
             │ score ∈ [0.0, 1.0]
             ▼
┌─────────────────────────────────┐
│  Router tri-critère             │
│  score < 0.40  → Gemma 3 4B     │
│  score < 0.75  → Gemma 3 12B    │  OpenRouter (1 clé)
│  score ≥ 0.75  → Gemma 3 27B    │
└────────────┬────────────────────┘
             │ réponse LLM
             ▼
┌─────────────────────────────────┐
│  LLM Juge (LOCAL — Ollama)      │  ~200ms, hors chemin critique
│  gemma2:2b — méthode RocketEval │
│  3 critères : coherence /       │
│  relevance / completeness       │
│  → score qualité 0.0–1.0        │
└─────────────────────────────────┘
             │
             ▼
       Auto-calibration seuils router
```

---

## Justifications des choix

### Complexity Estimator — sentence-transformers local

Un appel API distant (même Gemma 3 1B) implique une latence réseau de 100–500ms, incompatible
avec le budget < 50ms. `all-MiniLM-L6-v2` (~80MB) tourne sur CPU M5 en 5–15ms.

Le cache sémantique (similarité cosine ≥ 0.92) réduit à ~1ms sur les requêtes récurrentes.

À positionner dans le mémoire comme **pré-filtre sémantique** (embedding + classifier),
distinct des LLMs des tiers inférences — la distinction est académiquement honnête et défendable.

### Tiers LLM — Famille Gemma 3 homogène (OpenRouter)

**Argument jury :**
> *"Seule la taille paramétrique varie entre les tiers (4B / 12B / 27B). L'architecture,
> le tokenizer et les données d'entraînement sont identiques (famille Gemma 3, licence Apache 2.0).
> Tout écart de qualité mesuré est directement attribuable à la capacité du modèle."*

C'est la définition d'une variable contrôlée — le design expérimental le plus propre possible.

**Pourquoi OpenRouter et non Google AI Studio :**
Google AI Studio ne propose plus Gemma 3 en free tier depuis fin 2025 (uniquement Gemini 2.5 Flash).
OpenRouter propose les trois tailles Gemma 3 gratuitement sous licence Apache 2.0.

**Pourquoi un seul provider :**
Une seule clé API (`OPENROUTER_API_KEY`) — cohérence du code, un seul point de configuration,
pas de gestion multi-provider dans `app/config.py`.

### LLM Juge — Gemma-2-2B local (Ollama)

**Pourquoi local et non OpenRouter :**

1. **Conservation du quota** : OpenRouter = 200 req/day. Si le juge passe aussi par OpenRouter,
   chaque inférence génère un appel juge → quota divisé par 2. Pour 300 requêtes MMLU :
   - Juge local → 2 jours de benchmark
   - Juge via OpenRouter → 4+ jours de benchmark

2. **Reproductibilité** : version du modèle fixée dans Ollama, scores identiques entre runs.
   Un jury peut demander la reproductibilité — un modèle API peut changer silencieusement.

3. **Méthode RocketEval** (ICLR 2025) : Gemma-2-2B atteint 0.965 de corrélation Spearman
   avec les préférences humaines (comparable à GPT-4o), pour un coût 50× inférieur.
   C'est une référence académique citeable.

**Empreinte mémoire :** ~1.4GB quantized (q4), largement dans les 24GB du M5.

---

## Gestion du quota OpenRouter (200 req/day)

| Phase | Provider utilisé | Raison |
|---|---|---|
| Développement & tests unitaires | Ollama local (Gemma 3 4B q4) | Quota préservé, itérations rapides |
| Validation modules | OpenRouter (requêtes ciblées) | Vérification comportement API réel |
| Benchmarks MMLU finaux | OpenRouter (run nocturne) | 300 req → 2 nuits (150/nuit) |

Script de benchmark : délai configurable entre requêtes (`BENCH_DELAY_S`), flush Redis entre
chaque stratégie, reprise sur erreur 429.

---

## Variables d'environnement à ajouter

```bash
OPENROUTER_API_KEY="sk-or-..."        # clé unique OpenRouter
LLM_LIGHT_MODEL="google/gemma-3-4b-it:free"
LLM_BALANCED_MODEL="google/gemma-3-12b-it:free"
LLM_HEAVY_MODEL="google/gemma-3-27b-it:free"
COMPLEXITY_THRESHOLD_LIGHT=0.40       # score < 0.40 → tier léger
COMPLEXITY_THRESHOLD_HEAVY=0.75       # score ≥ 0.75 → tier lourd
JUDGE_MODEL="gemma2:2b"               # modèle Ollama local
OLLAMA_BASE_URL="http://localhost:11434"
```

---

## Phrase cible pour la soutenance

> *"Sur 250 requêtes MMLU, InferRouter-LLM réduit le coût d'inférence (temps × paramètres)
> de X% par rapport à Always-Heavy (Gemma 3 27B systématique), avec une dégradation de qualité
> inférieure à Y% mesurée par le LLM Juge (Gemma-2-2B, méthode RocketEval ICLR 2025)."*

---

## Décisions exclues

| Option écartée | Raison |
|---|---|
| Google AI Studio | Gemma 3 absent du free tier depuis fin 2025 |
| Groq comme provider principal | 1,000 req/day — insuffisant pour benchmarks + développement |
| LLM comme Complexity Estimator | Latence API > 100ms, incompatible avec < 50ms requis |
| Juge via OpenRouter | Divise le quota par 2, reproductibilité moindre |
| Familles mixtes (Gemma + Llama) | Design expérimental moins propre, variable non contrôlée |
