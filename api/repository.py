"""Stockage des prédictions et des décisions (traçabilité, RGPD, monitoring).

Deux implémentations interchangeables, avec exactement les mêmes méthodes :
- PostgresRepository : la vraie base de données (Docker Compose, production) ;
- InMemoryRepository : stockage en mémoire, pour les tests et le développement sans base.

L'API choisit l'une ou l'autre selon la variable d'environnement DATABASE_URL.
Ce découpage permet de tester toute l'API sans démarrer Postgres.

Sécurité : toutes les requêtes SQL sont PARAMÉTRÉES (les valeurs sont passées à part,
jamais collées dans le texte SQL), ce qui empêche les injections SQL (critère 2.5).
"""

import json
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id              BIGSERIAL PRIMARY KEY,
    player_id       UUID        NOT NULL,
    match_id        UUID        NOT NULL,
    suspicion_score REAL        NOT NULL,
    flagged         BOOLEAN     NOT NULL,
    model_version   TEXT        NOT NULL,
    features        JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_predictions_player ON predictions (player_id);
CREATE INDEX IF NOT EXISTS idx_predictions_created ON predictions (created_at);

CREATE TABLE IF NOT EXISTS decisions (
    id          BIGSERIAL PRIMARY KEY,
    player_id   UUID        NOT NULL,
    match_id    UUID        NOT NULL,
    decision    TEXT        NOT NULL,
    moderator   TEXT        NOT NULL,
    comment     TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decisions_player ON decisions (player_id);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryRepository:
    """Stockage en mémoire (perdu à l'arrêt) : pour les tests et le développement."""

    kind = "memoire"

    def __init__(self) -> None:
        self.predictions: list[dict] = []
        self.decisions: list[dict] = []

    def init_schema(self) -> None:
        """Rien à créer en mémoire."""

    def log_predictions(self, rows: list[dict]) -> None:
        self.predictions.extend({**row, "created_at": _now()} for row in rows)

    def add_decision(self, row: dict) -> dict:
        stored = {**row, "created_at": _now()}
        self.decisions.append(stored)
        return stored

    def get_player_data(self, player_id: str) -> dict:
        return {
            "predictions": [p for p in self.predictions if str(p["player_id"]) == player_id],
            "decisions": [d for d in self.decisions if str(d["player_id"]) == player_id],
        }

    def has_confirmed_cheat(self, player_id: str) -> bool:
        return any(
            str(d["player_id"]) == player_id and d["decision"] == "triche_confirmee"
            for d in self.decisions
        )

    def delete_player_data(self, player_id: str) -> tuple[int, int]:
        n_pred, n_dec = len(self.predictions), len(self.decisions)
        self.predictions = [p for p in self.predictions if str(p["player_id"]) != player_id]
        self.decisions = [d for d in self.decisions if str(d["player_id"]) != player_id]
        return n_pred - len(self.predictions), n_dec - len(self.decisions)

    def recent_predictions(self, limit: int) -> list[dict]:
        return sorted(self.predictions, key=lambda p: p["created_at"], reverse=True)[:limit]

    def purge_older_than(self, days: int) -> int:
        limit = _now() - timedelta(days=days)
        before = len(self.predictions)
        self.predictions = [p for p in self.predictions if p["created_at"] >= limit]
        return before - len(self.predictions)


class PostgresRepository:
    """Stockage dans Postgres. Une connexion courte est ouverte pour chaque opération."""

    kind = "postgres"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self) -> psycopg.Connection:
        # dict_row : chaque ligne lue est un dictionnaire {colonne: valeur}
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5)

    def init_schema(self) -> None:
        """Crée les tables si elles n'existent pas encore (au démarrage de l'API)."""
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def log_predictions(self, rows: list[dict]) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO predictions
                   (player_id, match_id, suspicion_score, flagged, model_version, features)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [
                    (
                        str(r["player_id"]),
                        str(r["match_id"]),
                        r["suspicion_score"],
                        r["flagged"],
                        r["model_version"],
                        json.dumps(r["features"]),
                    )
                    for r in rows
                ],
            )

    def add_decision(self, row: dict) -> dict:
        with self._connect() as conn:
            return conn.execute(
                """INSERT INTO decisions (player_id, match_id, decision, moderator, comment)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING player_id, match_id, decision, moderator, comment, created_at""",
                (
                    str(row["player_id"]),
                    str(row["match_id"]),
                    row["decision"],
                    row["moderator"],
                    row["comment"],
                ),
            ).fetchone()

    def get_player_data(self, player_id: str) -> dict:
        with self._connect() as conn:
            predictions = conn.execute(
                """SELECT player_id, match_id, suspicion_score, flagged, model_version,
                          features, created_at
                   FROM predictions WHERE player_id = %s ORDER BY created_at""",
                (player_id,),
            ).fetchall()
            decisions = conn.execute(
                """SELECT player_id, match_id, decision, moderator, comment, created_at
                   FROM decisions WHERE player_id = %s ORDER BY created_at""",
                (player_id,),
            ).fetchall()
        return {"predictions": predictions, "decisions": decisions}

    def has_confirmed_cheat(self, player_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM decisions
                   WHERE player_id = %s AND decision = 'triche_confirmee' LIMIT 1""",
                (player_id,),
            ).fetchone()
        return row is not None

    def delete_player_data(self, player_id: str) -> tuple[int, int]:
        # Les deux suppressions sont dans la même transaction : tout ou rien.
        with self._connect() as conn:
            n_pred = conn.execute(
                "DELETE FROM predictions WHERE player_id = %s", (player_id,)
            ).rowcount
            n_dec = conn.execute(
                "DELETE FROM decisions WHERE player_id = %s", (player_id,)
            ).rowcount
        return n_pred, n_dec

    def recent_predictions(self, limit: int) -> list[dict]:
        with self._connect() as conn:
            return conn.execute(
                """SELECT player_id, match_id, suspicion_score, flagged, model_version,
                          features, created_at
                   FROM predictions ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            ).fetchall()

    def purge_older_than(self, days: int) -> int:
        """Supprime les prédictions plus anciennes que la durée de conservation."""
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM predictions WHERE created_at < now() - make_interval(days => %s)",
                (days,),
            ).rowcount
