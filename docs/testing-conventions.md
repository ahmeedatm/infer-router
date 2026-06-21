# Cahier de tests — InferRouter-LLM

Conventions de test du projet. Section coût en tête : elle prime, car les
expériences appellent des API payantes (OpenRouter).

## Discipline de coût (API payantes) — RÈGLE DURE

Les appels aux modèles cibles via OpenRouter coûtent de l'argent réel. Tout
test ou expérience doit respecter ces règles, dans l'ordre.

1. **Tests unitaires : zéro appel réseau réel.** Toujours mocker OpenRouter et
   Ollama (`httpx.MockTransport`). Un test unitaire qui appelle une vraie API
   est un bug. Le juge local (Ollama/gemma2) est gratuit mais reste mocké en
   unitaire pour la vitesse et le déterminisme.

2. **Valider sur un échantillon AVANT le run complet.** Avant de lancer une
   expérience sur les 20 intents, la tester sur 1 à 4 cas (variable `SUBSET`).
   On ne paie le batch entier qu'une fois la logique confirmée sur le petit.

3. **Estimer et annoncer le coût avant tout run live.** Avant de lancer un
   script qui appelle OpenRouter : compter les appels × tokens × tarif, le dire,
   et demander l'accord d'Ahmed si l'estimation dépasse ~0,50 $. Vérifier le
   solde (`GET /api/v1/key`) avant un batch.

4. **Modèle le moins cher qui répond à la question.** Ne pas appeler le modèle
   lourd quand un léger suffit. Réserver le fort aux étapes qui l'exigent
   (génération de checklist, variantes dégradées).

5. **`max_tokens` ajusté à la tâche.** Ne pas demander 4096 tokens quand la
   sortie attendue en fait 200. Un cap trop haut gonfle le coût plafond et peut
   déclencher un refus 402 même quand le solde suffirait pour la vraie sortie.

6. **Réutiliser, ne pas régénérer.** Les réponses, checklists et paires déjà
   produites sont sauvegardées (`experiments/results/`). Re-noter des réponses
   stockées (changer seulement le juge local, gratuit) plutôt que rappeler les
   modèles cibles. Ne relancer une génération que si l'entrée a changé.

7. **Scripts live reprenables.** Tout script qui fait N appels payants écrit son
   résultat de façon incrémentale et saute le travail déjà fait, pour qu'une
   interruption (crédits épuisés, timeout) ne fasse pas repayer ce qui est
   acquis. Modèle de référence : `experiments/build_degraded_pairs.py`.

8. **Le juge local d'abord.** Toute mesure qui peut se faire avec le juge local
   (Ollama) sans rappeler les modèles cibles doit le faire. Le re-jugement de
   réponses stockées ne coûte rien.

## Conventions générales

- TDD : test d'abord (RED), implémentation (GREEN), nettoyage (REFACTOR).
- Lancer la suite : `.venv/bin/pytest tests/unit -q` (doit rester verte avant
  tout commit).
- Tests d'intégration live (`tests/integration/`) : skippés automatiquement si
  le service (Ollama, clé OpenRouter) est absent ; jamais requis pour la CI.
- Erreurs explicites, jamais silencieuses (cf. règles de style du projet).
