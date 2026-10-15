"""Schémas d'entrée et de sortie de l'API (validation automatique par Pydantic).

Chaque requête est vérifiée AVANT d'atteindre le modèle : type, bornes, valeurs autorisées.
Une donnée invalide est refusée avec une erreur 422 qui explique quel champ pose problème,
au lieu de produire une prédiction absurde (critères 2.3, 2.5 et 6.6).

Les bornes viennent de src/config.py : le contrat de données est défini à un seul endroit.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.config import NUMERIC_RANGES

MAX_BATCH_SIZE = 1_000  # protection contre les requêtes trop lourdes (déni de service)


def bounded(name: str, description: str):
    """Champ numérique borné selon le contrat de données (src/config.py)."""
    low, high = NUMERIC_RANGES[name]
    return Field(ge=low, le=high, description=description)


class MatchStats(BaseModel):
    """Statistiques d'un joueur sur un match terminé (contrat de données, section 4)."""

    # extra="forbid" : tout champ non prévu est refusé. En particulier, les variables
    # d'audit (âge, option d'accessibilité) ne peuvent pas être envoyées à l'API
    # (minimisation des données, cahier des charges section 8).
    # L'exemple pré-remplit le bouton "Try it out" de la documentation /docs.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "player_id": "8274bbcc-1f0e-4c1a-9a51-6f2d3c4b5a69",
                    "match_id": "0b9c2f4e-7d1a-4e3b-8c6f-2a1d9e8f7b65",
                    "accuracy": 0.31,
                    "headshot_rate": 0.42,
                    "kd_ratio": 2.4,
                    "kills_per_min": 1.2,
                    "damage_per_round": 165.0,
                    "avg_reaction_ms": 182.0,
                    "kills_through_smoke_ratio": 0.21,
                    "rank_tier": 6,
                    "account_age_days": 22,
                    "hours_played_total": 29.0,
                    "reports_received": 3,
                    "input_device": "clavier_souris",
                    "platform": "pc",
                }
            ]
        },
    )

    player_id: UUID = Field(description="Identifiant pseudonymisé du joueur")
    match_id: UUID = Field(description="Identifiant du match")
    accuracy: float = bounded("accuracy", "Précision des tirs (0 à 1)")
    headshot_rate: float = bounded("headshot_rate", "Part des éliminations par tir à la tête")
    kd_ratio: float = bounded("kd_ratio", "Ratio éliminations / morts")
    kills_per_min: float = bounded("kills_per_min", "Éliminations par minute")
    damage_per_round: float = bounded("damage_per_round", "Dégâts moyens par manche")
    avg_reaction_ms: float | None = Field(
        default=None,
        ge=NUMERIC_RANGES["avg_reaction_ms"][0],
        le=NUMERIC_RANGES["avg_reaction_ms"][1],
        description="Temps de réaction moyen en ms (null si télémétrie perdue)",
    )
    kills_through_smoke_ratio: float = bounded(
        "kills_through_smoke_ratio", "Part des éliminations à travers la fumée"
    )
    rank_tier: int = bounded("rank_tier", "Rang de 1 (débutant) à 8 (élite)")
    account_age_days: int = bounded("account_age_days", "Ancienneté du compte en jours")
    hours_played_total: float = bounded("hours_played_total", "Heures de jeu cumulées")
    reports_received: int = bounded("reports_received", "Signalements reçus pendant le match")
    input_device: Literal["clavier_souris", "manette"]
    platform: Literal["pc", "console"]


class BatchRequest(BaseModel):
    """Lot de fiches à scorer (file de revue)."""

    model_config = ConfigDict(extra="forbid")

    items: list[MatchStats] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class Reason(BaseModel):
    """Une raison lisible expliquant le score (voir src/explain.py)."""

    feature: str
    label: str
    value: float | str | None
    reference: float | None
    contribution: float
    direction: Literal["hausse", "baisse"]
    text: str


class Prediction(BaseModel):
    """Résultat pour une fiche (joueur, match).

    suspicion_score n'est PAS une probabilité calibrée : le modèle est entraîné avec des
    poids équilibrés, ses scores servent à CLASSER les fiches, pas à estimer un pourcentage
    de chances de tricher.
    """

    player_id: UUID
    match_id: UUID
    suspicion_score: float = Field(ge=0, le=1)
    flagged: bool = Field(description="True si le score dépasse le seuil de décision")
    priority: Literal["haute", "moyenne", "basse"]
    reasons: list[Reason]
    model_version: str


class BatchResponse(BaseModel):
    """File de revue : les fiches triées de la plus à la moins suspecte."""

    model_version: str
    count: int
    flagged_count: int
    predictions: list[Prediction]


class DecisionRequest(BaseModel):
    """Décision humaine d'un modérateur sur une fiche (article 22 du RGPD)."""

    model_config = ConfigDict(extra="forbid")

    match_id: UUID
    decision: Literal["triche_confirmee", "innocente", "a_approfondir"]
    moderator: str = Field(min_length=1, max_length=50, description="Identifiant du modérateur")
    comment: str = Field(default="", max_length=1_000)


class Decision(DecisionRequest):
    player_id: UUID
    created_at: datetime


class StoredPrediction(BaseModel):
    """Prédiction journalisée, telle que renvoyée au titre du droit d'accès."""

    player_id: UUID
    match_id: UUID
    suspicion_score: float
    flagged: bool
    model_version: str
    created_at: datetime
    features: dict


class PlayerData(BaseModel):
    """Toutes les données détenues sur un joueur (droit d'accès, article 15 du RGPD)."""

    player_id: UUID
    predictions: list[StoredPrediction]
    decisions: list[Decision]


class DeletionResult(BaseModel):
    """Résultat d'une demande d'effacement (article 17 du RGPD)."""

    player_id: UUID
    deleted_predictions: int
    deleted_decisions: int


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    model_loaded: bool
    model_version: str | None
    database: Literal["postgres", "memoire"]


class ValidationRequest(BaseModel):
    """Profils bruts importés (par exemple depuis un CSV) à vérifier avant scoring."""

    rows: list[dict] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class RowValidation(BaseModel):
    """Résultat de validation d'une ligne : conforme ou liste des erreurs en français."""

    row: int = Field(description="Numéro de la ligne (1 = première ligne de données)")
    valid: bool
    errors: list[str]


class ValidationReport(BaseModel):
    total: int
    valid_count: int
    invalid_count: int
    rows: list[RowValidation]
