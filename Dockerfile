# InferRouter-LLM — image d'exécution et de reproduction.
#
# Python 3.9 pour coller à l'environnement qui a produit les mesures publiées
# (requirements.txt est un jeu de versions résolu pour cet interpréteur).
#
# Deux cibles :
#   runtime  décision de routage, tests, benchmark hors ligne. Pas de torch,
#            image légère, aucun téléchargement de poids au build.
#   full     tout runtime + sentence-transformers et la pile scientifique,
#            nécessaire au réentraînement de l'estimateur combiné et aux
#            campagnes qui encodent des embeddings.
#
# Les LLM ne tournent jamais dans l'image. Le pool API passe par OpenRouter,
# les modèles locaux par l'Ollama de l'hôte (cf. docker-compose.yml).

# ── Base commune ─────────────────────────────────────────────────────────────
FROM python:3.9-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Un utilisateur non privilégié : rien ici n'a besoin de root.
RUN useradd --create-home --uid 1000 inferrouter

# ── Cible runtime ────────────────────────────────────────────────────────────
FROM base AS runtime

# Sous-ensemble suffisant pour la décision de routage, les appels LLM et les
# tests. scikit-learn tire numpy, scipy et joblib ; l'estimateur persisté est
# un RandomForest sur quatre attributs, il n'a besoin de rien d'autre.
COPY requirements-runtime.txt ./
RUN pip install -r requirements-runtime.txt

COPY --chown=inferrouter:inferrouter app/ ./app/
COPY --chown=inferrouter:inferrouter bench/ ./bench/
COPY --chown=inferrouter:inferrouter experiments/ ./experiments/
COPY --chown=inferrouter:inferrouter scripts/ ./scripts/
COPY --chown=inferrouter:inferrouter tests/ ./tests/
COPY --chown=inferrouter:inferrouter data/ ./data/
COPY --chown=inferrouter:inferrouter pytest.ini ./

# pytest écrit son cache dans le répertoire de travail : il doit appartenir à
# l'utilisateur non privilégié, sinon chaque run émet un avertissement.
RUN chown inferrouter:inferrouter /app

USER inferrouter

# Échec immédiat et lisible si l'estimateur persisté manque : sans lui, toute
# décision de routage est impossible.
RUN python -c "from experiments.train_complexity_estimator import predict_complexity; \
assert predict_complexity(['List the active cells on site A.'])[0] in ('simple','medium','complex')"

ENTRYPOINT ["python", "-m", "app.cli"]
CMD ["--help"]

# ── Cible full ───────────────────────────────────────────────────────────────
FROM runtime AS full

USER root
# torch et sentence-transformers ne servent qu'au réentraînement de la variante
# combinée attributs + embeddings. Le build est long et l'image dépasse le Go.
COPY requirements.txt ./
RUN pip install -r requirements.txt
USER inferrouter

ENTRYPOINT ["python", "-m", "app.cli"]
CMD ["--help"]
