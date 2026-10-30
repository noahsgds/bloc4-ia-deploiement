"""API Sentinel (FastAPI) : score de suspicion et explications pour les modérateurs.

Lancer en local :  uvicorn api.main:app --reload
Documentation interactive générée automatiquement : http://localhost:8000/docs

Routes :
    GET    /health                         le service fonctionne-t-il ? (sans clé)
    GET    /model-info                     version, mesures et équité du modèle en production
    POST   /predict                        score + 3 raisons pour 1 à 1 000 fiches
    POST   /players/{player_id}/decisions  décision humaine d'un modérateur
    GET    /players/{player_id}/data       droit d'accès RGPD
    DELETE /players/{player_id}/data       droit à l'effacement RGPD
    GET    /console/                       console de modération (page web)
"""

import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from api.repository import InMemoryRepository, PostgresRepository
from api.schemas import DecisionRequest, PredictRequest
from src.config import FEATURES, MODELS_DIR
from src.explain import explain
from src.model import load_champion

CONSOLE_DIR = Path(__file__).parent / "static" / "console"

# --- Journaux au format JSON (une ligne = un événement, jamais le contenu des fiches) ------
logger = logging.getLogger("sentinel")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def log(message: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, json.dumps({"message": message, **fields}, ensure_ascii=False, default=str))


# --- Sécurité -----------------------------------------------------------------------------


def expected_api_key() -> str:
    """Clé lue dans la variable d'environnement API_KEY (fichier .env), jamais dans le code."""
    key = os.environ.get("API_KEY", "")
    if not key or key == "change-me":
        raise RuntimeError("API_KEY n'est pas configurée (voir .env.example).")
    return key


def require_api_key(key: str | None = Depends(APIKeyHeader(name="X-API-Key", auto_error=False))):
    """Refuse la requête (401) sans la bonne clé dans l'en-tête X-API-Key.

    compare_digest compare en temps constant : impossible de deviner la clé caractère
    par caractère en mesurant le temps de réponse.
    """
    if key is None or not secrets.compare_digest(key, expected_api_key()):
        raise HTTPException(401, "Clé d'API absente ou invalide (en-tête X-API-Key).")


# La console n'autorise que ses propres fichiers : aucun script externe ou injecté (XSS).
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# La page /docs (générée par FastAPI) charge Swagger UI depuis cdn.jsdelivr.net et lance un
# petit script intégré à la page : la règle stricte ci-dessus l'afficherait vide. On autorise
# ces deux exceptions sur cette page seulement ; la console garde la règle stricte.
DOCS_PATHS = ("/docs", "/docs/oauth2-redirect")
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)

# Messages d'erreur en français pour les erreurs de format les plus courantes.
ERRORS_FR = {
    "missing": "champ obligatoire manquant",
    "extra_forbidden": "champ non autorisé",
    "greater_than_equal": "valeur trop petite",
    "less_than_equal": "valeur trop grande",
    "literal_error": "valeur non autorisée",
    "uuid_parsing": "identifiant invalide",
    "float_parsing": "nombre attendu",
    "int_parsing": "nombre entier attendu",
    "int_from_float": "nombre entier attendu",
    "int_type": "nombre entier attendu",
    "float_type": "nombre attendu",
    "too_long": "trop de fiches (1 000 maximum)",
}


# --- Application --------------------------------------------------------------------------


def create_app(repository=None, models_dir=MODELS_DIR) -> FastAPI:
    """Construit l'application. Les tests y injectent un stockage en mémoire."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        expected_api_key()  # arrêt immédiat si la clé n'est pas configurée
        url = os.environ.get("DATABASE_URL")
        app.state.db = repository or (PostgresRepository(url) if url else InMemoryRepository())
        app.state.db.init_schema()
        app.state.model, app.state.meta = load_champion(models_dir)
        log("modèle chargé", version=app.state.meta["version"])
        yield

    app = FastAPI(title="Sentinel — détection de triche", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def journal(request: Request, call_next):
        """Journalise chaque requête (route, statut, durée) et ajoute les en-têtes de sécurité."""
        start = time.perf_counter()
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", request.url.path)  # pas l'id joueur
        duration = round((time.perf_counter() - start) * 1000, 1)
        log("requête", route=route, status=response.status_code, ms=duration)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path in DOCS_PATHS:
            response.headers["Content-Security-Policy"] = DOCS_CSP
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_data(request: Request, error: RequestValidationError):
        """Données invalides : 422 avec, pour chaque problème, où il est et pourquoi."""
        problems = []
        for e in error.errors():
            where = ".".join(str(part) for part in e["loc"][1:])  # ex. "fiches.2.accuracy"
            problems.append(
                {"loc": e["loc"], "message": f"{where} : {ERRORS_FR.get(e['type'], e['msg'])}"}
            )
        return JSONResponse(status_code=422, content={"detail": problems})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        """Erreur imprévue : tracée dans les journaux, message neutre pour l'appelant."""
        log("erreur interne", logging.ERROR, path=request.url.path, error=repr(error))
        return JSONResponse(status_code=500, content={"detail": "Erreur interne journalisée."})

    secured = [Depends(require_api_key)]

    @app.get("/health", tags=["Service"])
    def health(request: Request):
        return {"status": "ok", "model_version": request.app.state.meta["version"]}

    @app.get("/model-info", tags=["Service"], dependencies=secured)
    def model_info(request: Request):
        meta = request.app.state.meta
        public = ["version", "model_name", "created_at", "threshold", "test_metrics",
                  "baseline_test_metrics", "fairness", "acceptance", "data"]  # fmt: skip
        return {key: meta[key] for key in public}

    @app.post("/predict", tags=["Prédiction"], dependencies=secured)
    def predict(body: PredictRequest, request: Request):
        """Score de suspicion et 3 raisons par fiche, triées de la plus à la moins suspecte.

        Le score sert à TRIER la file de revue : ce n'est pas une probabilité, et le modèle
        ne sanctionne jamais (décision humaine obligatoire).
        """
        model, meta = request.app.state.model, request.app.state.meta
        fiches = [f.model_dump(mode="json") for f in body.fiches]
        X = pd.DataFrame(fiches)[FEATURES].astype({"avg_reaction_ms": float})  # None -> NaN
        scores = model.predict_proba(X)[:, 1]
        reasons = explain(model, X, meta["explain_info"])
        threshold = meta["threshold"]

        results = [
            {
                "player_id": fiche["player_id"],
                "match_id": fiche["match_id"],
                "suspicion_score": round(float(score), 4),
                "flagged": bool(score >= threshold),
                "priority": "haute"
                if score >= threshold
                else "moyenne"
                if score >= threshold / 2
                else "basse",
                "reasons": fiche_reasons,
                "model_version": meta["version"],
            }
            for fiche, score, fiche_reasons in zip(fiches, scores, reasons)
        ]
        # Journal des prédictions (traçabilité, droit d'accès). Si la base est en panne, les
        # modérateurs reçoivent quand même les scores et l'incident est journalisé.
        try:
            request.app.state.db.log_predictions(
                [
                    {
                        **{
                            k: r[k]
                            for k in (
                                "player_id",
                                "match_id",
                                "suspicion_score",
                                "flagged",
                                "model_version",
                            )
                        },
                        "features": {k: f[k] for k in FEATURES},
                    }
                    for f, r in zip(fiches, results)
                ]  # fmt: skip
            )
        except Exception as error:  # noqa: BLE001
            log("journalisation impossible", logging.ERROR, error=repr(error))

        results.sort(key=lambda r: r["suspicion_score"], reverse=True)
        return {"model_version": meta["version"], "count": len(results), "predictions": results}

    @app.post(
        "/players/{player_id}/decisions", status_code=201, tags=["Modération"], dependencies=secured
    )
    def add_decision(player_id: UUID, body: DecisionRequest, request: Request):
        """Enregistre la décision du modérateur : le modèle ne sanctionne jamais seul."""
        stored = request.app.state.db.add_decision({"player_id": player_id, **body.model_dump()})
        log("décision enregistrée", decision=body.decision)
        return stored

    @app.get("/players/{player_id}/data", tags=["RGPD"], dependencies=secured)
    def access(player_id: UUID, request: Request):
        """Droit d'accès (art. 15) : tout ce que Sentinel conserve sur ce joueur."""
        log("droit d'accès exercé", player_id=player_id)  # preuve de traitement (art. 5.2)
        return {"player_id": player_id, **request.app.state.db.get_player_data(str(player_id))}

    @app.delete("/players/{player_id}/data", tags=["RGPD"], dependencies=secured)
    def erase(player_id: UUID, request: Request):
        """Droit à l'effacement (art. 17).

        Exception : si une triche a été confirmée, les éléments sont gardés jusqu'à la fin
        de la procédure de contestation (art. 17.3.e) ; l'API répond 409 et l'explique.
        """
        db = request.app.state.db
        if db.has_confirmed_cheat(str(player_id)):
            log("effacement différé (contestation)", player_id=player_id)
            raise HTTPException(409, "Effacement différé : sanction en cours de contestation.")
        n_predictions, n_decisions = db.delete_player_data(str(player_id))
        log("droit à l'effacement exercé", player_id=player_id, predictions=n_predictions)
        return {"player_id": player_id, "deleted_predictions": n_predictions,
                "deleted_decisions": n_decisions}  # fmt: skip

    app.mount("/console", StaticFiles(directory=CONSOLE_DIR, html=True), name="console")

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/console/")

    return app


app = create_app()
