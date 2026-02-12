# 1. Image de base : Python 3.11 léger (Debian Slim)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
# Force les logs à s'afficher en temps réel dans le terminal
ENV PYTHONUNBUFFERED=1

# 3. Dossier de travail dans le conteneur
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 5. Copie et installation des dépendances Python
# On le fait AVANT de copier le code pour profiter du cache Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copie du reste du code source
COPY . .

# 7. Commande de démarrage
# On utilise Uvicorn pour lancer FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]