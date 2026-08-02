# InferRouter-LLM

Routage d'intents réseau en langage naturel vers un pool de LLM, sous garantie
de qualité. Le système choisit le modèle le moins cher dont la qualité attendue
dépasse un plancher fixé par la criticité de l'intent.

Travail de mémoire de Master (CNAM Paris, Réseaux & Objets Connectés). Le
rapport complet est dans `docs/InferRouter-LLM.pdf`.

## Ce que fait le système

Un intent du type « corrèle les alarmes de congestion RAN du site B avec les
pertes UPF et propose un redimensionnement de slice » arrive avec deux
métadonnées opérateur : son domaine réseau et sa criticité. Le système en estime
la complexité sémantique, puis arbitre :

```
minimiser le coût   sous contrainte   q(m) >= q_min(criticité)
                                      latence(m) <= L_max
                                      coût(m)    <= C_max
```

La criticité fixe le plancher (`low` 0,35 / `med` 0,50 / `high` 0,70). Un intent
peu critique part au modèle léger et coûte 170 fois moins ; un intent critique
exige le lourd. C'est le curseur économie/qualité de l'opérateur.

Le routeur ne maximise pas la qualité. Avec un modèle lourd fort, maximiser la
qualité renvoie tout au lourd et le routage disparaît.

## Démarrage rapide

Deux chemins au choix. En local :

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-runtime.txt
```

`requirements-runtime.txt` suffit pour faire tourner le routeur et les tests.
`requirements.txt` ajoute torch et sentence-transformers, utiles seulement pour
réentraîner la variante combinée de l'estimateur.

Par Docker, sans rien installer (voir la section Docker plus bas) :

```bash
docker compose run --rm cli "Show the PRB utilisation of cell 12 on site A." --domain ran --criticality low --stage decision
```

La décision de routage ne demande ni clé API ni Ollama :

```bash
.venv/bin/python -m app.cli "Show the PRB utilisation of cell 12 on site A." --domain ran --criticality low --stage decision
```

Sortie : les attributs lus par l'estimateur, la classe prédite, le tableau des
candidats avec leur qualité attendue, leur coût et leur admissibilité SLA, et le
modèle retenu avec sa justification.

Pour aller jusqu'à l'appel du modèle et sa notation par le juge, il faut Ollama
et quatre modèles locaux (environ 21 Go) :

```bash
ollama pull gemma2:2b && ollama pull qwen2.5:14b-instruct && ollama pull qwen2.5:7b-instruct && ollama pull gemma2:9b
```

```bash
.venv/bin/python -m app.cli "Show the PRB utilisation of cell 12 on site A." --domain ran --criticality low
```

Environ 20 secondes, aucun coût. Le pipeline complet s'affiche étape par étape :
estimation, arbitrage, appel réel, checklist RocketEval critère par critère,
puis comparaison entre la qualité promise et la qualité mesurée.

## Le CLI

`python -m app.cli "<intent>" [options]`

| Option | Défaut | Effet |
|---|---|---|
| `--domain` | `core` | Domaine réseau : `ran`, `core`, `security`, `slice` |
| `--criticality` | `med` | `low`, `med`, `high` ; fixe le plancher `q_min` |
| `--stage` | `judge` | `decision`, `execute` ou `judge` |
| `--provider` | `local` | `local` (Ollama, gratuit) ou `api` (OpenRouter, facturé) |
| `--pool` | `generic` | `generic` (2 tiers calibrés) ou `default` (+ 4 spécialistes) |
| `--q-min` | dérivé | Force le plancher au lieu de le dériver de la criticité |
| `--l-max`, `--c-max` | illimité | Budgets SLA (ms, USD par appel) |
| `--max-tokens` | 4096 | Plafond de génération du modèle cible |
| `--expected-complexity` | l'estimation | Étiquette de vérité-terrain, si connue |
| `--json` | non | Trace brute en JSON au lieu du rapport lisible |

Le domaine et la criticité ne sont pas devinés. Ce sont des métadonnées
opérateur, pas des propriétés du texte : les inférer reviendrait à décider du
SLA à la place de l'opérateur. Seule la complexité est estimée depuis l'énoncé.

Quelques usages typiques :

```bash
.venv/bin/python -m app.cli "Reroute core NF traffic after the DC-2 outage." --domain core --criticality high --stage decision
```

```bash
.venv/bin/python -m app.cli "List the active gNBs on site A." --l-max 12000 --stage decision
```

Un budget de latence serré exclut le lourd du jeu admissible, ce que la colonne
`SLA` du tableau montre directement.

```bash
.venv/bin/python -m app.cli "Create a URLLC slice under 5 ms for factory X." --domain slice --criticality high --json
```

En mode `local`, les deux tiers du pool sont servis par le couple Ollama du banc
réseau réel (gemma2:2b pour le léger, qwen2.5:14b-instruct pour le lourd). La
décision, elle, reste prise sur les profils coût/latence calibrés du pool API :
seul le modèle qui sert le tier change, pas l'arbitrage.

En mode `api`, le pool réel est utilisé (qwen-2.5-72b et claude-opus-4.8) et
`OPENROUTER_API_KEY` doit être renseignée.

## Composants

L'estimateur de complexité prédit `simple`, `medium` ou `complex` à partir
d'attributs indépendants de la longueur : nombre d'entités réseau, nombre de
contraintes, nombre de domaines croisés, nombre de valeurs numériques. Coût
mesuré 3,4 ms par intent, en régime établi.

Le routeur tri-critère écarte d'abord les candidats hors budget SLA, garde ceux
qui atteignent le plancher de qualité, et retient le moins cher. Si aucun
candidat n'atteint le plancher, il bascule au mieux-disant plutôt que de refuser
l'intent.

Le LLM-Juge évalue une réponse par la méthode RocketEval : un modèle tiers
génère une checklist de critères vérifiables propres à l'intent, un petit modèle
local (gemma2:9b) coche chaque critère, et `q` vaut la proportion de critères
validés. Le juge sert à la calibration hors ligne, pas à la décision : au
runtime le routeur lit la matrice de qualité déjà mesurée
(`config.QUALITY_LIGHT_BY_COMPLEXITY`).

## Résultats mesurés

Benchmark sur 74 intents, juge gemma2:9b, checklists neutres générées par
claude-sonnet-4.6 :

| Stratégie | Qualité | Coût moyen | Latence P50 |
|---|---|---|---|
| Always-Heavy | 0,88 | 0,0285 $ | 19,1 s |
| InferRouter | 0,78 | 0,0201 $ | 19,5 s |
| Random | 0,65 | 0,0124 $ | 11,9 s |
| Always-Light | 0,46 | 0,0002 $ | 7,9 s |

Le gain est économique : 30 % de coût en moins que le tout-lourd, pour 0,10 de
qualité en moins. Ni la latence ni la qualité ne s'améliorent, les deux tiers du
pool étant lents.

Le résultat le plus intéressant du travail concerne le choix du modèle léger.
Sur six candidats testés, le meilleur en absolu (deepseek-v3.2, robuste et moins
cher) casse le routage : InferRouter tombe sous le tirage aléatoire. Comme ce
modèle est bon partout uniformément, aucun signal n'indique où le lourd apporte
quelque chose. À l'inverse qwen-2.5-72b, moins bon mais dont la qualité décroît
avec la complexité (0,64 / 0,39 / 0,32), fait fonctionner le routage. Le bon
modèle léger n'est pas le plus fort, c'est celui dont la faiblesse est
prédictible.

## Structure du dépôt

```
app/
  cli/                  CLI interactif (pipeline, rendu, trace, providers)
  config.py             tous les paramètres, surchargeables par variable d'env
  llm/
    schema.py           Intent, ModelResponse, JudgeScore (pydantic, frozen)
    intents.py          chargement et validation du jeu d'intents
    features.py         attributs de complexité
    prompting.py        framing des prompts et conventions d'id de modèle
    openrouter_client.py  appel des LLM cibles (API)
    ollama_client.py    appel des modèles locaux
    judge.py            LLM-Juge (RocketEval, notation absolue et par paires)
    checklist.py        génération de checklist par intent
    pool.py             pool de modèles (generic_pool et default_pool)
    policy.py           qualité attendue par candidat
    router.py           sélection sous contraintes (décision pure)
    inferrouter.py      orchestrateur de la décision
    sdn_action.py       traduction d'une réponse en action réseau structurée

bench/                  banc de validation en réseau émulé (Mininet + OVS)
data/                   datasets d'intents, estimateur persisté
experiments/            campagnes de mesure, results/ contient les mesures
tests/unit/             tests sans réseau ni service
tests/integration/      tests nécessitant Ollama ou le banc
docs/                   rapport de mémoire et findings

Dockerfile              cibles runtime et full
docker-compose.yml      services cli, tests, bench, train, ollama
requirements-runtime.txt  dépendances d'exécution (sans torch)
requirements.txt          + pile embeddings
```

`data/complexity_estimator.joblib` et `experiments/results/` sont versionnés :
sans eux, un clone frais ne peut ni router un intent ni rejouer une mesure.
L'estimateur est déterministe (`random_state=42`) et pèse 1,1 Mo.

Le pool par défaut du CLI est `generic_pool`, qui ne contient que les deux tiers
réellement calibrés. `default_pool` ajoute quatre spécialistes de domaine dont
la qualité (0,92) est une valeur de prototype jamais mesurée : elle domine toute
comparaison et masquerait le finding ci-dessus. À n'utiliser que pour illustrer
l'architecture cible.

## Configuration

Tout passe par `app/config.py`, surchargeable par variables d'environnement.
Celles qui comptent en pratique :

| Variable | Défaut | Rôle |
|---|---|---|
| `OPENROUTER_API_KEY` | vide | Requise pour `--provider api` |
| `MODEL_LIGHT` | `qwen/qwen-2.5-72b-instruct` | Tier léger du pool |
| `MODEL_HEAVY` | `anthropic/claude-opus-4.8` | Tier lourd du pool |
| `JUDGE_MODEL` | `gemma2:9b` | Juge local |
| `CHECKLIST_MODEL` | `anthropic/claude-sonnet-4.6` | Génère les checklists |
| `OLLAMA_HOST` | `http://localhost:11434` | Serveur Ollama |
| `QMIN_LOW/MED/HIGH` | 0,35 / 0,50 / 0,70 | Planchers de qualité |

Ne pas rétrograder `JUDGE_MODEL` vers gemma2:2b : ce modèle a montré 40 à 50 %
d'accord seulement et invalide toute mesure de qualité.

## Docker

Deux cibles dans le `Dockerfile`. `runtime` (561 Mo) porte la décision de
routage, les appels LLM, le juge, les tests et le benchmark hors ligne. `full`
(1,5 Go) ajoute torch et sentence-transformers pour réentraîner l'estimateur
combiné.

Aucun LLM ne tourne dans l'image. Le pool API passe par OpenRouter, les modèles
locaux par un serveur Ollama : celui de l'hôte par défaut, via
`host.docker.internal`, puisque c'est lui qui détient déjà les 21 Go de poids.

```bash
docker compose run --rm cli "Create a URLLC slice under 5 ms for factory X." --domain slice --criticality high --stage decision
```

```bash
docker compose run --rm tests
```

```bash
docker compose run --rm bench
```

Le service `bench` rejoue le benchmark hors ligne et reproduit les quatre lignes
du tableau ci-dessus sans un seul appel payant. C'est la vérification la plus
directe que les chiffres du rapport sont reconstructibles.

Sur une machine sans Ollama installé, un serveur conteneurisé est disponible en
profil :

```bash
docker compose --profile ollama up -d ollama
```

```bash
docker compose --profile ollama exec ollama ollama pull gemma2:2b
```

Il faut alors pointer `OLLAMA_HOST` sur `http://ollama:11434` dans `.env`.

## Tests

```bash
.venv/bin/pytest -q
```

326 tests unitaires, sans réseau ni service : les clients HTTP sont injectables
et les tests passent par `httpx.MockTransport`. Les tests d'intégration
(`tests/integration/`) demandent Ollama vivant, ou le banc Mininet pour ceux
marqués `bench`, et ne sont pas collectés par défaut.

```bash
.venv/bin/ruff check .
```

## Reproduire les campagnes

`experiments/` contient les scripts de mesure : fiabilité du juge, séparabilité
de la complexité, calibration de la qualité par modèle, frontière de Pareto,
comparaison des stratégies. Les résultats déjà produits sont dans
`experiments/results/`.

Ces scripts appellent des API payantes. Ils valident sur un petit échantillon
avant tout passage à l'échelle, réutilisent les artefacts existants et sont
reprenables. Le benchmark hors ligne rejoue les mesures sans nouvel appel :

```bash
.venv/bin/python -m experiments.exp_benchmark_offline
```

Pour réentraîner l'estimateur de complexité :

```bash
.venv/bin/python -m experiments.train_complexity_estimator
```

## Banc de validation en réseau émulé

`bench/` applique les plans produits par les modèles directement en règles
OpenFlow sur Open vSwitch, dans une VM Linux avec Mininet, et vérifie dans le
plan de données que l'intent est réellement satisfait. Le modèle cible émet un
plan de plusieurs opérations sur sept verbes (autoriser et bloquer, y compris
sur un port applicatif, plafonner un débit, dupliquer un flux vers une sonde,
imposer un chemin, marquer une priorité), appliqué sur une topologie en losange
à deux chemins. Le provisionnement de la VM Lima est dans `bench/provision/`.

Chaque vérification est validée par deux contrôles avant toute mesure. Le
contrôle négatif rejoue le jeu avec un plan sans effet réseau et doit tout faire
échouer ; le contrôle positif le rejoue avec le plan dérivé de la vérité terrain
et doit tout faire réussir. Les deux sont gratuits, aucun n'appelle de modèle :

```bash
python experiments/run_realworld_validation.py --strategy noop
limactl shell inferbench bash -c 'cd /opt/infer-router && sudo python3 -m bench.run_bench --strategy noop'
```

Ce dispositif a écarté plusieurs vérifications qui produisaient un résultat
lisible sans dépendre du modèle évalué, dont un test de chemin satisfait par
l'acheminement par défaut.

Résultat sur 24 intents stratifiés, pool de production : le modèle lourd réalise
79 % des intents, InferRouter 75 %, le léger 67 %. Le léger produit en outre un
plan inexploitable sur 24, rejeté avant toute application. Router vers un léger
faible a donc un coût mesurable dans le plan de données, pas seulement une note
de juge plus basse.

## Limites connues

L'estimateur persisté dans `data/complexity_estimator.joblib` est la variante à
quatre attributs de fond, mesurée à 65-73 % en validation croisée. C'est un
choix assumé du prototype (attributs lisibles en termes métier, insensibles à la
verbosité par construction, cf. §5.2 du rapport), pas la variante combinée
attributs + embeddings qui atteint 85-94 %. En pratique le CLI classe donc assez
grossièrement : deux intents de difficulté très différente peuvent recevoir la
même classe, et la décision de routage qui suit sera la même.

Le juge local distingue de façon fiable une bonne réponse d'une réponse
clairement mauvaise (100 % en discrimination grossière), ce qui suffit au
routage. Il ne détecte pas une erreur subtile injectée dans une réponse par
ailleurs correcte : sur vingt paires correct/dégradé, il rend vingt égalités.
Un juge fort accessible par API en tranche la moitié, donc la capacité du
modèle déplace la limite sans la lever.

Les spécialistes de domaine sont mesurés : un cadrage d'expertise gagne 0,038
sur son domaine et perd 0,137 hors de lui. La pénalité vaut 3,6 fois le gain,
si bien que la spécialisation ne paie que si le routage par domaine vise juste.
Ce gain reste en revanche sous la résolution du juge, et ne ressort donc pas
du score agrégé.

Le gain économique dépend de la composition du flux traité : 30 % d'économie
sur un jeu, 11 % sur un autre, parce que seuls les intents à la fois simples et
peu critiques descendent au tier économique.

Les latences mesurées viennent d'un MacBook Air M5 et de l'API OpenRouter. Elles
sont indicatives, pas représentatives d'un déploiement en périphérie.

## Licence

MIT, voir [LICENSE](LICENSE).
