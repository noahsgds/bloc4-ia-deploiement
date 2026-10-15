"""Authentification par clé d'API (critères 2.5 et 4.6).

Chaque appel (sauf /health) doit fournir l'en-tête  X-API-Key: <clé>.
La clé est lue dans la variable d'environnement API_KEY, jamais écrite dans le code :
en local elle vient du fichier .env (non versionné), en CI des secrets GitHub.
"""

import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def expected_api_key() -> str:
    """Clé attendue. Refuse de fonctionner sans clé configurée (pas de valeur par défaut)."""
    key = os.environ.get("API_KEY", "")
    if not key or key == "change-me":
        raise RuntimeError("API_KEY n'est pas configurée (voir .env.example).")
    return key


def require_api_key(provided: str | None = Security(api_key_header)) -> str:
    """Dépendance FastAPI : vérifie la clé, sinon renvoie 401.

    secrets.compare_digest compare les deux chaînes en temps constant : un attaquant ne
    peut pas deviner la clé caractère par caractère en mesurant le temps de réponse.
    """
    if provided is None or not secrets.compare_digest(provided, expected_api_key()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé d'API absente ou invalide (en-tête X-API-Key).",
        )
    return provided
