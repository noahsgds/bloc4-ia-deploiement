# Image de l'API Sentinel
# Construire : docker build -t sentinel-api .
# (en pratique, utiliser docker compose up --build, voir docker-compose.yml)

# Image officielle Python 3.11, variante "slim" : légère, mêmes versions qu'en local.
FROM python:3.11-slim

# Python : pas de fichiers .pyc, logs affichés immédiatement ; pip : pas de cache.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NUMBA_CACHE_DIR=/tmp/numba

WORKDIR /app

# Utilisateur sans privilèges : si l'API était compromise, l'attaquant ne serait pas root.
RUN useradd --create-home --uid 1000 sentinel

# Dépendances d'abord : cette couche n'est reconstruite que si requirements-api.txt change
# (les modifications du code ne déclenchent pas une réinstallation complète).
COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

# Code et modèle champion versionné.
COPY src/ src/
COPY api/ api/
COPY models/ models/

USER sentinel
EXPOSE 8000

# Docker vérifie toutes les 30 s que l'API répond ; sinon le conteneur est "unhealthy".
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# 2 processus pour traiter des requêtes en parallèle.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
