"""Tests du stockage (prédictions, décisions, droits RGPD, purge).

Les mêmes tests s'appliquent aux deux implémentations :
- en mémoire : toujours exécutés ;
- Postgres : exécutés seulement si la variable TEST_DATABASE_URL pointe vers une base
  de test (c'est le cas dans l'intégration continue). La base est vidée avant chaque test.

Lancer : pytest tests/test_repository.py -v
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from api.repository import InMemoryRepository, PostgresRepository

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(params=["memoire", "postgres"])
def repository(request):
    if request.param == "memoire":
        return InMemoryRepository()
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL non définie : tests Postgres ignorés")
    repo = PostgresRepository(TEST_DATABASE_URL)
    repo.init_schema()
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE predictions, decisions")
    return repo


def prediction(player_id: str) -> dict:
    return {
        "player_id": player_id,
        "match_id": str(uuid.uuid4()),
        "suspicion_score": 0.8,
        "flagged": True,
        "model_version": "v1",
        "features": {"accuracy": 0.3, "avg_reaction_ms": None},
    }


def test_journalisation_et_droit_d_acces(repository):
    player = str(uuid.uuid4())
    repository.log_predictions([prediction(player), prediction(player)])
    repository.log_predictions([prediction(str(uuid.uuid4()))])  # un autre joueur

    data = repository.get_player_data(player)
    assert len(data["predictions"]) == 2
    assert data["predictions"][0]["features"]["accuracy"] == 0.3
    assert data["predictions"][0]["features"]["avg_reaction_ms"] is None


def test_effacement_ne_touche_que_le_joueur(repository):
    player, other = str(uuid.uuid4()), str(uuid.uuid4())
    repository.log_predictions([prediction(player), prediction(other)])
    repository.add_decision(
        {
            "player_id": player,
            "match_id": str(uuid.uuid4()),
            "decision": "innocente",
            "moderator": "mod-01",
            "comment": "",
        }
    )
    assert repository.delete_player_data(player) == (1, 1)
    assert repository.get_player_data(player) == {"predictions": [], "decisions": []}
    assert len(repository.get_player_data(other)["predictions"]) == 1


def test_triche_confirmee_detectee(repository):
    player = str(uuid.uuid4())
    assert repository.has_confirmed_cheat(player) is False
    repository.add_decision(
        {
            "player_id": player,
            "match_id": str(uuid.uuid4()),
            "decision": "triche_confirmee",
            "moderator": "mod-02",
            "comment": "",
        }
    )
    assert repository.has_confirmed_cheat(player) is True


def test_injection_sql_sans_effet(repository):
    """Une valeur malveillante est traitée comme du texte, jamais exécutée."""
    malicious = "x'; DROP TABLE predictions; --"
    player = str(uuid.uuid4())
    repository.log_predictions([prediction(player)])
    repository.add_decision(
        {
            "player_id": str(uuid.uuid4()),
            "match_id": str(uuid.uuid4()),
            "decision": "innocente",
            "moderator": malicious,
            "comment": malicious,
        }
    )
    assert len(repository.get_player_data(player)["predictions"]) == 1  # table intacte


def test_purge_des_predictions_anciennes(repository):
    player = str(uuid.uuid4())
    repository.log_predictions([prediction(player), prediction(player)])
    old = datetime.now(timezone.utc) - timedelta(days=400)
    if isinstance(repository, InMemoryRepository):
        repository.predictions[0]["created_at"] = old
    else:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute(
                "UPDATE predictions SET created_at = %s "
                "WHERE id = (SELECT min(id) FROM predictions)",
                (old,),
            )
    assert repository.purge_older_than(days=365) == (1, 0)
    assert len(repository.get_player_data(player)["predictions"]) == 1


def test_purge_des_decisions_anciennes(repository):
    player = str(uuid.uuid4())
    for decision in ["innocente", "triche_confirmee"]:
        repository.add_decision(
            {
                "player_id": player,
                "match_id": str(uuid.uuid4()),
                "decision": decision,
                "moderator": "mod-01",
                "comment": "",
            }
        )
    old = datetime.now(timezone.utc) - timedelta(days=400)
    if isinstance(repository, InMemoryRepository):
        repository.decisions[0]["created_at"] = old
    else:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute(
                "UPDATE decisions SET created_at = %s WHERE id = (SELECT min(id) FROM decisions)",
                (old,),
            )
    assert repository.purge_older_than(days=365) == (0, 1)
    assert len(repository.get_player_data(player)["decisions"]) == 1
