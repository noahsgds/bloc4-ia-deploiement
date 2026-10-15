"""API de prédiction Sentinel (FastAPI).

Lancer en local :
    uvicorn api.main:app --reload
Documentation interactive générée automatiquement : http://localhost:8000/docs

Routes :
    GET    /health                        état du service (sans authentification)
    GET    /model-info                    version, métriques et équité du modèle en production
    POST   /predict                       score d'une fiche (joueur, match) + 3 raisons
    POST   /predict/batch                 file de revue : lot trié du plus au moins suspect
    POST   /players/{player_id}/decisions décision humaine d'un modérateur
    GET    /players/{player_id}/data      droit d'accès (RGPD art. 15)
    DELETE /players/{player_id}/data      droit à l'effacement (RGPD art. 17)
"""

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from api.repository import InMemoryRepository, PostgresRepository
from api.schemas import (
    BatchRequest,
    BatchResponse,
    Decision,
    DecisionRequest,
    DeletionResult,
    Health,
    MatchStats,
    PlayerData,
    Prediction,
)
from api.security import expected_api_key, require_api_key
from api.service import ModelService
from src.config import FEATURES, MODELS_DIR


class JsonFormatter(logging.Formatter):
    """Logs au format JSON (une ligne = un événement) : faciles à filtrer et à analyser."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {"level": record.levelname, "message": record.getMessage()}
        entry.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


logger = logging.getLogger("sentinel")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def log(level: int, message: str, **fields) -> None:
    logger.log(level, message, extra={"extra_fields": fields})


def build_repository():
    """Postgres si DATABASE_URL est défini, sinon stockage en mémoire."""
    database_url = os.environ.get("DATABASE_URL")
    return PostgresRepository(database_url) if database_url else InMemoryRepository()


def create_app(repository=None, models_dir=MODELS_DIR) -> FastAPI:
    """Construit l'application. Les paramètres permettent aux tests d'injecter leurs objets."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        expected_api_key()  # arrêt immédiat si la clé n'est pas configurée
        app.state.repository = repository or build_repository()
        app.state.repository.init_schema()
        try:
            app.state.service = ModelService(models_dir)
            log(logging.INFO, "modèle chargé", model_version=app.state.service.version)
        except FileNotFoundError as error:
            # L'API démarre quand même (pour exposer /health) mais refuse de prédire.
            app.state.service = None
            log(logging.ERROR, "modèle introuvable", error=str(error))
        yield

    app = FastAPI(
        title="Sentinel — API de détection de triche",
        description="Score de suspicion et explications pour la file de revue des modérateurs.",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        """Journalise chaque requête : route, statut, durée. Jamais le contenu (données)."""
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        log(
            logging.INFO,
            "requête",
            request_id=request_id,
            method=request.method,
            route=getattr(route, "path", request.url.path),  # modèle de route, pas l'id joueur
            status=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        """Erreur imprévue : journalisée avec sa trace, message neutre pour l'appelant."""
        log(logging.ERROR, "erreur interne", path=request.url.path, error=repr(error))
        logger.exception(error)
        return JSONResponse(
            status_code=500, content={"detail": "Erreur interne. L'incident a été journalisé."}
        )

    def get_service(request: Request) -> ModelService:
        service = request.app.state.service
        if service is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Aucun modèle chargé.")
        return service

    def log_predictions(request: Request, records: list[dict], results: list[dict]) -> None:
        """Journalise les prédictions (traçabilité + monitoring de la dérive).

        Si la base est indisponible, la prédiction est quand même renvoyée : le service
        reste disponible pour les modérateurs, et l'incident est journalisé.
        """
        rows = [
            {
                **{k: result[k] for k in ("player_id", "match_id", "model_version")},
                "suspicion_score": result["suspicion_score"],
                "flagged": result["flagged"],
                "features": {feature: record[feature] for feature in FEATURES},
            }
            for record, result in zip(records, results)
        ]
        try:
            request.app.state.repository.log_predictions(rows)
        except Exception as error:  # noqa: BLE001 - toute erreur de stockage est tolérée ici
            log(logging.ERROR, "journalisation des prédictions impossible", error=repr(error))

    # --- Routes -----------------------------------------------------------------------

    @app.get("/health", response_model=Health, tags=["Service"])
    def health(request: Request):
        service = request.app.state.service
        body = {
            "status": "ok" if service else "degraded",
            "model_loaded": service is not None,
            "model_version": service.version if service else None,
            "database": request.app.state.repository.kind,
        }
        return JSONResponse(body, status_code=200 if service else 503)

    @app.get("/model-info", tags=["Service"], dependencies=[Depends(require_api_key)])
    def model_info(service: ModelService = Depends(get_service)):
        return service.info()

    @app.post(
        "/predict",
        response_model=Prediction,
        tags=["Prédiction"],
        dependencies=[Depends(require_api_key)],
    )
    def predict(stats: MatchStats, request: Request, service=Depends(get_service)):
        record = stats.model_dump()
        result = service.predict([record])
        log_predictions(request, [record], result)
        return result[0]

    @app.post(
        "/predict/batch",
        response_model=BatchResponse,
        tags=["Prédiction"],
        dependencies=[Depends(require_api_key)],
    )
    def predict_batch(
        batch: BatchRequest,
        request: Request,
        with_reasons: bool = Query(True, description="Calculer les 3 raisons de chaque fiche"),
        service=Depends(get_service),
    ):
        records = [item.model_dump() for item in batch.items]
        results = service.predict(records, with_reasons=with_reasons)
        log_predictions(request, records, results)
        ordered = sorted(results, key=lambda r: r["suspicion_score"], reverse=True)
        return {
            "model_version": service.version,
            "count": len(ordered),
            "flagged_count": sum(r["flagged"] for r in ordered),
            "predictions": ordered,
        }

    @app.post(
        "/players/{player_id}/decisions",
        response_model=Decision,
        status_code=status.HTTP_201_CREATED,
        tags=["Modération"],
        dependencies=[Depends(require_api_key)],
    )
    def add_decision(player_id: UUID, decision: DecisionRequest, request: Request):
        """Enregistre la décision HUMAINE : le modèle ne sanctionne jamais seul."""
        row = {"player_id": player_id, **decision.model_dump()}
        stored = request.app.state.repository.add_decision(row)
        log(logging.INFO, "décision enregistrée", decision=decision.decision)
        return stored

    @app.get(
        "/players/{player_id}/data",
        response_model=PlayerData,
        tags=["RGPD"],
        dependencies=[Depends(require_api_key)],
    )
    def player_data(player_id: UUID, request: Request):
        """Droit d'accès : toutes les prédictions et décisions concernant un joueur."""
        data = request.app.state.repository.get_player_data(str(player_id))
        log(logging.INFO, "droit d'accès exercé")
        return {"player_id": player_id, **data}

    @app.delete(
        "/players/{player_id}/data",
        response_model=DeletionResult,
        tags=["RGPD"],
        dependencies=[Depends(require_api_key)],
    )
    def delete_player_data(player_id: UUID, request: Request):
        """Droit à l'effacement.

        Exception : si une triche a été confirmée, les éléments sont conservés le temps
        de la procédure de contestation (cahier des charges, section 8).
        """
        repository = request.app.state.repository
        if repository.has_confirmed_cheat(str(player_id)):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Effacement différé : une sanction pour triche est en cours, les éléments "
                "sont conservés jusqu'à la fin de la procédure de contestation.",
            )
        n_pred, n_dec = repository.delete_player_data(str(player_id))
        log(logging.INFO, "droit à l'effacement exercé", deleted_predictions=n_pred)
        return {"player_id": player_id, "deleted_predictions": n_pred, "deleted_decisions": n_dec}

    return app


app = create_app()
