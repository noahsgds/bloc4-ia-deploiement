"""Format des données reçues par l'API, vérifié automatiquement par Pydantic.

Chaque requête est contrôlée AVANT d'atteindre le modèle : types, bornes, valeurs
autorisées. Une donnée invalide est refusée (erreur 422 avec un message en français)
au lieu de produire un score absurde. Les bornes viennent de src/config.py.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.config import NUMERIC_RANGES

MAX_BATCH_SIZE = 1_000  # protège le service contre les requêtes trop lourdes

EXAMPLE = {
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


def bounded(name: str, default=...):
    """Champ numérique borné selon le contrat de données."""
    low, high = NUMERIC_RANGES[name]
    return Field(default, ge=low, le=high)


class MatchStats(BaseModel):
    """Une fiche : les statistiques d'un joueur sur un match terminé.

    extra="forbid" : tout champ non prévu est refusé. On ne peut donc pas envoyer l'âge
    ou l'option d'accessibilité à l'API (minimisation des données).
    """

    model_config = ConfigDict(extra="forbid")

    player_id: UUID  # identifiant pseudonyme
    match_id: UUID
    accuracy: float = bounded("accuracy")
    headshot_rate: float = bounded("headshot_rate")
    kd_ratio: float = bounded("kd_ratio")
    kills_per_min: float = bounded("kills_per_min")
    damage_per_round: float = bounded("damage_per_round")
    avg_reaction_ms: float | None = bounded("avg_reaction_ms", default=None)  # peut manquer
    kills_through_smoke_ratio: float = bounded("kills_through_smoke_ratio")
    rank_tier: int = bounded("rank_tier")
    account_age_days: int = bounded("account_age_days")
    hours_played_total: float = bounded("hours_played_total")
    reports_received: int = bounded("reports_received")
    input_device: Literal["clavier_souris", "manette"]
    platform: Literal["pc", "console"]


class PredictRequest(BaseModel):
    """Une ou plusieurs fiches à analyser (jusqu'à 1 000)."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"fiches": [EXAMPLE]}]}
    )

    fiches: list[MatchStats] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class DecisionRequest(BaseModel):
    """Décision HUMAINE d'un modérateur sur une fiche (article 22 du RGPD)."""

    model_config = ConfigDict(extra="forbid")

    match_id: UUID
    decision: Literal["triche_confirmee", "innocente", "a_approfondir"]
    moderator: str = Field(min_length=1, max_length=50)
    comment: str = Field(default="", max_length=1_000)
