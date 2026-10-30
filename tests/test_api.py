"""Tests de l'API : sécurité, prédiction, erreurs, droits RGPD, décisions humaines.

L'API est testée avec le stockage en mémoire : aucun serveur ni base à démarrer.
"""

import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.repository import InMemoryRepository
from api.schemas import EXAMPLE
from src.config import FEATURES, MODELS_DIR
from src.data import generate_dataset

KEY = {"X-API-Key": "cle-de-test"}
CHAMPION = json.loads((MODELS_DIR / "champion.json").read_text())["version"]


@pytest.fixture(scope="module")
def client():
    patch = pytest.MonkeyPatch()
    patch.setenv("API_KEY", "cle-de-test")
    with TestClient(create_app(repository=InMemoryRepository())) as test_client:
        yield test_client
    patch.undo()


@pytest.fixture(scope="module")
def fiches():
    df = generate_dataset(n_matches=200, seed=11)
    records = df[["player_id", "match_id", *FEATURES]].to_dict(orient="records")
    for r in records:
        if np.isnan(r["avg_reaction_ms"]):
            r["avg_reaction_ms"] = None
    return records


def test_sante_sans_cle(client):
    assert client.get("/health").json() == {"status": "ok", "model_version": CHAMPION}


def test_cle_obligatoire(client):
    assert client.post("/predict", json={"fiches": [EXAMPLE]}).status_code == 401
    bad = {"X-API-Key": "mauvaise"}
    assert client.post("/predict", json={"fiches": [EXAMPLE]}, headers=bad).status_code == 401


def test_prediction_score_raisons_et_tri(client, fiches):
    response = client.post("/predict", json={"fiches": fiches}, headers=KEY)
    assert response.status_code == 200
    predictions = response.json()["predictions"]
    assert len(predictions) == len(fiches)
    scores = [p["suspicion_score"] for p in predictions]
    assert scores == sorted(scores, reverse=True)  # file de revue triée
    first = predictions[0]
    assert 0 <= first["suspicion_score"] <= 1
    assert first["priority"] in {"haute", "moyenne", "basse"}
    assert len(first["reasons"]) == 3 and first["model_version"] == CHAMPION


def test_donnees_invalides_refusees_en_francais(client):
    bad = {**EXAMPLE, "accuracy": 3, "platform": "xbox"}
    response = client.post("/predict", json={"fiches": [EXAMPLE, bad]}, headers=KEY)
    assert response.status_code == 422
    messages = [d["message"] for d in response.json()["detail"]]
    assert "fiches.1.accuracy : valeur trop grande" in messages
    assert any("platform" in m for m in messages)


def test_minimisation_champ_non_prevu_refuse(client):
    response = client.post(
        "/predict", json={"fiches": [{**EXAMPLE, "age_band": "16-17"}]}, headers=KEY
    )
    assert response.status_code == 422


def test_lot_trop_gros_refuse(client):
    response = client.post("/predict", json={"fiches": [EXAMPLE] * 1_001}, headers=KEY)
    assert response.status_code == 422


def test_droits_d_acces_et_d_effacement(client):
    player = str(uuid.uuid4())
    fiche = {**EXAMPLE, "player_id": player, "match_id": str(uuid.uuid4())}
    client.post("/predict", json={"fiches": [fiche]}, headers=KEY)

    data = client.get(f"/players/{player}/data", headers=KEY).json()
    assert len(data["predictions"]) == 1
    assert "age_band" not in data["predictions"][0]["features"]

    erased = client.delete(f"/players/{player}/data", headers=KEY).json()
    assert erased["deleted_predictions"] == 1
    assert client.get(f"/players/{player}/data", headers=KEY).json()["predictions"] == []


def test_effacement_differe_si_triche_confirmee(client):
    player = str(uuid.uuid4())
    decision = {
        "match_id": str(uuid.uuid4()),
        "decision": "triche_confirmee",
        "moderator": "mod-01",
    }
    assert (
        client.post(f"/players/{player}/decisions", json=decision, headers=KEY).status_code == 201
    )
    assert client.delete(f"/players/{player}/data", headers=KEY).status_code == 409


def test_decision_humaine_controlee(client):
    player = str(uuid.uuid4())
    bad = {"match_id": str(uuid.uuid4()), "decision": "bannir_automatiquement", "moderator": "m"}
    assert client.post(f"/players/{player}/decisions", json=bad, headers=KEY).status_code == 422


def test_console_protegee_par_en_tetes_de_securite(client):
    response = client.get("/console/")
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_page_docs_affichee_mais_console_reste_stricte(client):
    """/docs peut charger Swagger UI ; la console, elle, n'autorise aucun script externe."""
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    console = client.get("/console/")
    assert "cdn.jsdelivr.net" not in console.headers["content-security-policy"]


def test_base_en_panne_le_service_repond_quand_meme(client, monkeypatch):
    def broken(rows):
        raise ConnectionError("base indisponible")

    monkeypatch.setattr(client.app.state.db, "log_predictions", broken)
    assert client.post("/predict", json={"fiches": [EXAMPLE]}, headers=KEY).status_code == 200
