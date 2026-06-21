# Spike risk-first — note de findings (juin 2026)

Validation empirique des trois hypothèses critiques d'InferRouter-LLM avant
d'investir dans le dataset complet et le système complet (cadre : ADR-005).

Protocole : 20 intents réseau écrits à la main (RAN, cœur, sécurité, slice ;
gradient simple/medium/complex). Deux modèles cibles via OpenRouter, un léger
(`meta-llama/llama-3.2-3b-instruct`) et un lourd (`anthropic/claude-sonnet-4.6`).
Chaque réponse notée par le LLM-Juge local (`gemma2:2b` via Ollama, méthode
RocketEval simplifiée à 4 critères Y/N). Jugement de référence produit en aveugle
par un modèle fort (Claude Opus), réponses anonymisées et mélangées A/B.

## H-A — Fiabilité du LLM-Juge : ÉCHEC (alerte rouge)

Accord juge gemma2:2b ↔ référence forte : **40 % (8/20)**, sous le seuil de 60 %.
Par complexité : simple 57 %, medium 29 %, complex 33 %. L'accord se dégrade
quand l'intent se complexifie.

Le problème n'est pas du bruit aléatoire, c'est une mauvaise calibration
systématique. Trois défauts observés, sur des réponses non tronquées :

- Le juge récompense les hallucinations. Sur `core-read-amf-registrations`, la
  réponse légère invente un chiffre (« 23 UEs enregistrés ») que le modèle ne
  peut pas connaître ; le juge lui attribue q = 1,00. Idem sur
  `slice-read-active-count` (« 15 slices » inventées, q = 1,00) alors que la
  réponse honnête qui explique comment obtenir la donnée reçoit 0,75.
- Le juge classe parfois la pire réponse au-dessus de la meilleure. Sur
  `security-isolate-compromised-slice`, un runbook d'incident complet et correct
  obtient 0,50, tandis qu'une réponse vague en obtient 1,00.
- Le juge sature. Sur les intents complexes, il note la plupart des réponses
  autour de 0,88 à 1,00 sans discriminer, ce qui explique l'effondrement de
  l'accord sur cette tranche.

Le smoke test trivial (bonne réponse vs hors-sujet « capitale de la France »)
passait pourtant à 1,00 contre 0,00. Le juge distingue donc le grossier, mais
pas la qualité entre deux réponses techniques plausibles. C'est insuffisant
pour fonder un routage par `argmax q`.

### Test d'un juge plus gros : gemma2:9b

Mêmes 40 réponses, mêmes verdicts de référence, seul le modèle juge change.
Accord : **50 % (10/20)**, contre 40 % pour le 2b. Progrès net sur le complexe
(33 % → 67 %), mais recul sur le simple (57 % → 43 %). Toujours sous le seuil.

Les 10 désaccords restants tombent dans deux cas structurels, que la taille du
modèle ne corrige pas :

- Aveuglement à l'hallucination. Sur `core-read-amf-registrations` et
  `core-read-upf-status`, le 9b note encore 1,00 la réponse qui invente un
  chiffre, et 0,25 la réponse honnête. Sans ancrage factuel, le juge ne peut
  pas voir qu'une donnée est fabriquée : ses critères (correction, complétude)
  semblent remplis par une réponse fausse mais confiante.
- Saturation et égalités. Six intents finissent à score identique
  (0,25/0,25 ou 1,00/1,00). L'échelle à quatre critères Y/N est trop grossière
  pour départager deux réponses plausibles.

### Lecture et leviers

Le levier n'est donc pas surtout la taille du juge, c'est la méthode :
- Checklist générée par intent via un LLM fort (RocketEval complet) plutôt
  qu'une checklist fixe de quatre critères. Une checklist taillée pour l'intent
  contient des items vérifiables qu'une réponse inventée échoue.
- Notation par paires (A vs B) plutôt que scores absolus indépendants : connue
  pour être plus fiable et pour supprimer les égalités.

Limite de la mesure elle-même : la référence préfère le lourd sur les 20 cas
(aucune variance), en partie à cause des troncatures du léger. La métrique
d'accord est donc dégénérée (un juge disant toujours « lourd » obtiendrait
100 %). Le passage 40 % → 50 % reste interprétable (même protocole, seul le juge
change), mais l'absolu est faussé bas. Un re-run propre (léger non tronqué)
donnera une référence à vraie variance et un accord plus informatif.

## H-B — Prémisse du routage : non concluant (confondu)

La référence préfère le modèle lourd sur les 20 intents, y compris les simples.
Le motif attendu (le léger suffit sur le simple, le lourd ne paie que sur le
complexe) n'apparaît pas sur ce couple de modèles.

Deux réserves empêchent de conclure :

- Plusieurs réponses du modèle léger sont tronquées (41 à 78 caractères, coupées
  en pleine phrase). La cause n'est pas tranchée (limite de jetons côté client
  non fixée explicitement, ou arrêt prématuré du petit modèle). Tant qu'elle
  n'est pas levée, l'infériorité du léger est en partie un artefact.
- L'écart de coût est réel et net : le lourd coûte deux à trois ordres de
  grandeur de plus par réponse. Si un léger correctement borné devenait
  acceptable sur les intents simples, le routage garderait une valeur côté coût
  même sans écart de qualité.

À refaire proprement : fixer `max_tokens`, et éventuellement un léger plus
robuste, avant de statuer sur H-B.

## Mise à jour — re-run propre (v2) et faille de conception de l'expérience A

Un second run a fixé un budget de jetons généreux (`max_tokens` = 4096) pour
écarter toute troncature. Trois constats.

D'abord, le cap initial à 1024 jetons était une erreur : il tronquait le modèle
lourd sur les intents complexes (réponses de 2000 à 2700 jetons), sans rien
régler côté léger. Corrigé à 4096, plus aucune troncature du lourd.

Ensuite, les réponses courtes du modèle léger ne sont pas un artefact de cap.
À température nulle, `llama-3.2-3b` s'arrête spontanément sur quatre intents RAN
(41 à 111 caractères, coupés en pleine phrase) et continue d'inventer des
données sur les intents de lecture (un nombre d'UE, un nombre de slices). C'est
un comportement intrinsèque du petit modèle, pas un défaut de mesure.

Enfin, sur ces données propres, le juge gemma2:2b reproduit exactement le défaut
d'aveuglement : q = 1,00 pour les réponses qui inventent un chiffre, contre 0,50
pour la réponse honnête correspondante. En revanche il pénalise bien les
réponses tronquées (0,25 à 0,50). Le défaut est donc ciblé sur la fabrication,
pas sur l'incomplétude. Cette preuve est robuste, indépendante du jugement de
référence.

Faille de conception à corriger. Opposer un modèle fort à un modèle nettement
plus faible produit une référence sans variance : le lourd l'emporte sur les
20 intents. La métrique « pourcentage d'accord » devient dégénérée, un juge qui
dirait toujours « lourd » obtiendrait 100 %. Pour mesurer correctement la
fiabilité du juge, il faut lui soumettre des paires de réponses de qualité
proche et variable, pas un duel déséquilibré. Conception retenue pour la suite :
construire des paires contrôlées (une réponse correcte contre une variante où
l'on injecte une erreur précise, ou deux modèles de capacité voisine), de sorte
qu'un bon juge doive discriminer finement et qu'un mauvais échoue de façon
mesurable.

## RocketEval complet : le correctif validé

Chantier 2 de l'ADR-006. On remplace la checklist fixe de quatre critères par
une checklist générée par intent via un modèle fort (claude-sonnet-4.6), gradée
ensuite par le même petit juge local gemma2:2b. Mêmes 20 intents, mêmes réponses
v2, même référence.

Accord avec la référence : **90 % (18/20)**, contre 40 % pour la checklist fixe
en 2b et 50 % en 9b. Par complexité : simple 100 %, medium 100 %, complexe 67 %.

Deux enseignements. D'abord, le petit juge de 2 milliards de paramètres, doté
d'une bonne checklist, dépasse largement le juge de 9 milliards à checklist
fixe. Le levier de fiabilité est la méthode d'évaluation, pas la taille du
modèle, conformément à RocketEval. Ensuite, l'aveuglement à l'hallucination est
corrigé : sur les intents de lecture, une réponse qui invente un chiffre tombe
de 1,00 à 0,43, et l'ordre correct (lourd au-dessus du léger) est rétabli, y
compris sur le cas que le juge inversait auparavant. Cette baisse ciblée est une
preuve robuste, indépendante de la métrique d'accord.

Réserves. La référence reste déséquilibrée (le lourd l'emporte sur les 20), donc
les 90 % mesurent surtout que le juge préfère désormais le lourd, pas une
discrimination fine. Les deux désaccords résiduels sont des égalités sur intents
complexes (les deux réponses notées 0,12), où gemma2:2b peine à grader une
checklist de huit items contre une réponse longue. La validation propre, sur des
paires de qualité proche, et l'étape de repondération supervisée de RocketEval
(étape 3, non implémentée) restent à faire pour une mesure de niveau publication.

Verdict révisé du spike : le LLM-Juge local est récupérable. RocketEval complet
fait passer l'accord de 40 % à 90 % sans changer de modèle. La voie est ouverte
pour reprendre le reste du cœur, une fois la validation propre faite.

## Validation propre : discrimination sur paires contrôlées (expérience D)

Le test précédent opposait un modèle fort à un faible, ce qui gonfle l'accord.
Test décisif : pour chaque intent, on dégrade la bonne réponse en y injectant
une seule erreur (chiffre faux, étape retirée, affirmation fausse), puis on
demande au juge RocketEval complet de classer l'originale et la dégradée. La
vérité-terrain est connue, les deux textes sont quasi identiques, le juge ne
peut plus gagner en préférant le plus long.

Résultat : préférence correcte **35 %** (7/20), égalités 40 %, inversions 25 %.
Par type d'erreur : chiffre faux 57 % (0 inversion), affirmation fausse 33 %,
étape manquante 14 % avec quatre inversions. Retirer une étape critique fait
souvent monter le score de la version dégradée, parce que le texte paraît plus
propre et que le petit juge ne relie pas la checklist à l'omission.

Lecture. Le 90 % obtenu en opposant fort et faible était optimiste. Sur une
dégradation subtile d'une réponse longue, le juge gemma2:2b ne discrimine pas,
même avec une checklist générée.

## Verdict consolidé sur le juge (H-A)

Deux régimes, à distinguer nettement.

- Discrimination grossière (un candidat nettement meilleur qu'un autre) :
  fiable. RocketEval complet corrige l'aveuglement à l'hallucination et classe
  correctement fort contre faible.
- Discrimination fine (détecter une erreur isolée, servir d'oracle de qualité
  absolue) : non fiable avec ce petit juge, à 35 %.

Conséquence pour le système. Le routage ne demande que la discrimination
grossière : pour un intent donné, l'agent spécialisé est-il nettement meilleur
que le générique. Le juge peut donc servir de signal de routage, en comparaison
relative entre candidats, pas de score de qualité absolu sur lequel poser un
seuil. Cela oriente la contribution C3 et l'usage de q dans le routeur.

Pistes pour relever la discrimination fine, si on en a besoin plus tard : juge
de grading un peu plus gros (gemma2:9b), étape 3 de RocketEval (repondération
supervisée des items), ou découpe des réponses longues avant grading.

## H-C — Séparabilité de la complexité : non testé

Reporté. L'expérience C (embeddings sentence-transformers) n'a pas été lancée,
la priorité étant le risque n°1. À mener quand H-A aura une réponse.

## Verdict global : ADJUST

Le spike a fait son travail : il a tué la naïveté la plus coûteuse avant qu'elle
ne coûte. Le LLM-Juge local en 2 milliards de paramètres, tel qu'instancié ici,
n'est pas assez fiable pour arbitrer le routage. Avant toute suite (dataset,
estimateur, benchmarks), il faut d'abord rendre le juge fiable, parce que toute
la chaîne en dépend. Le reste du squelette (client OpenRouter, routeur,
chargement d'intents) fonctionne et reste réutilisable.

Prochaines actions :
1. Instruire un ADR sur la fiabilisation du juge (modèle plus gros ou RocketEval
   complet), puis re-mesurer l'accord.
2. Re-lancer l'expérience A avec `max_tokens` fixé pour lever le confondu H-B.
3. Lancer l'expérience C une fois le juge stabilisé.

Limite de méthode : le jugement de référence vient d'un modèle fort, pas d'un
humain. C'est une calibration petit-juge contre juge-fort, pratique standard,
mais un échantillon validé par un expert humain reste souhaitable pour l'argument
définitif du mémoire.
