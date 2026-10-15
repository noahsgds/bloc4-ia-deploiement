"""Tests de l'API (critères 2.2, 2.3, 2.5, 5.2 ; critères d'acceptation CA-03, CA-04, CA-05, CA-11).

L'API est testée avec le stockage en mémoire : aucun serveur ni base de données à démarrer.
Le TestClient de FastAPI envoie de vraies requêtes HTTP à l'application, en local.

Lancer : pytest tests/test_api.py -v
"""

import time
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.repository import InMemoryRepository
from api.schemas import MAX_BATCH_SIZE
from src.config import FEATURES
from src.data.generate import generate_dataset

API_KEY = "cle-de-test"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture(scope="module")
def client():
    """Application démarrée une fois pour tout le module, avec une clé de test."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("API_KEY", API_KEY)
    app = create_app(repository=InMemoryRepository())
    with TestClient(app) as test_client:  # "with" déclenche le démarrage (chargement du modèle)
        yield test_client
    monkeypatch.undo()


@pytest.fixture(scope="module")
def payloads():
    """Fiches synthétiques au format JSON attendu par l'API."""
    df = generate_dataset(n_matches=300, seed=11)
    records = df[["player_id", "match_id", *FEATURES]].to_dict(orient="records")
    for record in records:
        if np.isnan(record["avg_reaction_ms"]):
            record["avg_reaction_ms"] = None  # JSON : null
    return records


# --- Service ---------------------------------------------------------------------------


def test_health_sans_cle(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["model_loaded"] is True


def test_model_info(client):
    response = client.get("/model-info", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "v1"
    assert "pr_auc" in body["test_metrics"]
    assert "explain_info" not in body  # les références internes ne sont pas exposées


def test_documentation_disponible(client):
    assert client.get("/openapi.json").status_code == 200


# --- Sécurité (CA-04) ----------------------------------------------------------------


def test_sans_cle_401(client, payloads):
    assert client.post("/predict", json=payloads[0]).status_code == 401


def test_mauvaise_cle_401(client, payloads):
    response = client.post("/predict", json=payloads[0], headers={"X-API-Key": "pirate"})
    assert response.status_code == 401


def test_demarrage_refuse_sans_cle_configuree(monkeypatch):
    monkeypatch.setenv("API_KEY", "change-me")  # valeur d'exemple de .env.example
    app = create_app(repository=InMemoryRepository())
    with pytest.raises(RuntimeError, match="API_KEY"):
        with TestClient(app):
            pass


# --- Prédiction (CA-03) ----------------------------------------------------------------


def test_prediction_complete(client, payloads):
    response = client.post("/predict", json=payloads[0], headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["suspicion_score"] <= 1
    assert body["priority"] in {"haute", "moyenne", "basse"}
    assert body["model_version"] == "v1"
    assert len(body["reasons"]) == 3
    assert all(reason["text"] for reason in body["reasons"])


def test_temps_de_reaction_absent_accepte(client, payloads):
    payload = {**payloads[1], "avg_reaction_ms": None}
    assert client.post("/predict", json=payload, headers=HEADERS).status_code == 200


def test_lot_trie_du_plus_au_moins_suspect(client, payloads):
    response = client.post(
        "/predict/batch?with_reasons=false", json={"items": payloads[:100]}, headers=HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    scores = [p["suspicion_score"] for p in body["predictions"]]
    assert scores == sorted(scores, reverse=True)
    assert body["count"] == 100
    assert body["flagged_count"] == sum(p["flagged"] for p in body["predictions"])


def test_lot_avec_raisons(client, payloads):
    response = client.post("/predict/batch", json={"items": payloads[:5]}, headers=HEADERS)
    assert all(len(p["reasons"]) == 3 for p in response.json()["predictions"])


# --- Validation des entrées (CA-04, critère 2.3) -----------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"accuracy": 1.7},  # précision de 170 % : impossible
        {"rank_tier": 12},  # rang inexistant
        {"platform": "mobile"},  # plateforme inconnue
        {"player_id": "pas-un-uuid"},
        {"kd_ratio": "beaucoup"},  # texte au lieu d'un nombre
    ],
)
def test_entree_invalide_422(client, payloads, change):
    response = client.post("/predict", json={**payloads[0], **change}, headers=HEADERS)
    assert response.status_code == 422


def test_champ_manquant_422(client, payloads):
    payload = {k: v for k, v in payloads[0].items() if k != "headshot_rate"}
    response = client.post("/predict", json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert "headshot_rate" in response.text  # le message indique le champ fautif


def test_variables_d_audit_refusees(client, payloads):
    """Minimisation : l'API refuse de recevoir l'âge ou l'option d'accessibilité."""
    for extra in ({"age_band": "16-17"}, {"accessibility_mode": True}):
        response = client.post("/predict", json={**payloads[0], **extra}, headers=HEADERS)
        assert response.status_code == 422


def test_lot_trop_gros_422(client, payloads):
    items = (payloads * 4)[: MAX_BATCH_SIZE + 1]
    response = client.post("/predict/batch", json={"items": items}, headers=HEADERS)
    assert response.status_code == 422


def test_lot_vide_422(client):
    assert client.post("/predict/batch", json={"items": []}, headers=HEADERS).status_code == 422


# --- Décisions humaines et RGPD (CA-11, critères 5.1 et 5.2) -----------------------------


def test_droit_d_acces_et_effacement(client, payloads):
    payload = {**payloads[2], "player_id": str(uuid.uuid4())}
    player_id = payload["player_id"]
    client.post("/predict", json=payload, headers=HEADERS)

    access = client.get(f"/players/{player_id}/data", headers=HEADERS)
    assert access.status_code == 200
    assert len(access.json()["predictions"]) == 1
    assert "accuracy" in access.json()["predictions"][0]["features"]

    deletion = client.delete(f"/players/{player_id}/data", headers=HEADERS)
    assert deletion.status_code == 200
    assert deletion.json()["deleted_predictions"] == 1

    after = client.get(f"/players/{player_id}/data", headers=HEADERS)
    assert after.json()["predictions"] == []


def test_effacement_differe_si_triche_confirmee(client, payloads):
    payload = {**payloads[3], "player_id": str(uuid.uuid4())}
    player_id = payload["player_id"]
    client.post("/predict", json=payload, headers=HEADERS)
    decision = {
        "match_id": payload["match_id"],
        "decision": "triche_confirmee",
        "moderator": "mod-01",
        "comment": "Aimbot visible sur la rediffusion",
    }
    created = client.post(f"/players/{player_id}/decisions", json=decision, headers=HEADERS)
    assert created.status_code == 201

    response = client.delete(f"/players/{player_id}/data", headers=HEADERS)
    assert response.status_code == 409
    assert "contestation" in response.json()["detail"]


def test_decision_invalide_422(client, payloads):
    player_id = payloads[0]["player_id"]
    decision = {"match_id": payloads[0]["match_id"], "decision": "bannir", "moderator": "mod-01"}
    response = client.post(f"/players/{player_id}/decisions", json=decision, headers=HEADERS)
    assert response.status_code == 422


# --- Temps de réponse (CA-05, critère 2.2) ------------------------------------------------


def test_latence_api_p95_sous_200_ms(client, payloads):
    """Requête HTTP complète : validation + score + 3 explications + journalisation."""
    durations = []
    for payload in payloads[:50]:
        start = time.perf_counter()
        client.post("/predict", json=payload, headers=HEADERS)
        durations.append((time.perf_counter() - start) * 1000)
    assert np.percentile(durations, 95) < 200


# --- Validation d'un import et console ------------------------------------------------


def test_validation_ligne_par_ligne(client, payloads):
    """Chaque ligne est jugée séparément, avec des motifs de rejet en français."""
    as_csv = {k: ("" if v is None else str(v)) for k, v in payloads[0].items()}
    rows = [
        as_csv,
        {**as_csv, "accuracy": "1.7"},
        {**as_csv, "platform": "mobile"},
        {**as_csv, "rank_tier": ""},
        {**as_csv, "age_band": "16-17"},
    ]
    response = client.post("/profiles/validate", json={"rows": rows}, headers=HEADERS)
    assert response.status_code == 200
    report = response.json()
    assert (report["total"], report["valid_count"], report["invalid_count"]) == (5, 1, 4)
    errors = [r["errors"] for r in report["rows"]]
    assert errors[0] == []
    assert "accuracy : doit être inférieur ou égal à 1.0" in errors[1]
    assert "ou" in errors[2][0] and "platform" in errors[2][0]
    assert errors[3] == ["rank_tier : valeur manquante"]
    assert "non autorisé" in errors[4][0]


def test_validation_protegee_par_cle(client, payloads):
    assert client.post("/profiles/validate", json={"rows": [payloads[0]]}).status_code == 401


def test_console_servie_avec_en_tetes_de_securite(client):
    response = client.get("/console/")
    assert response.status_code == 200
    assert "Sentinel" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


def test_racine_redirige_vers_la_console(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/console/"


def test_fichier_d_exemple_conforme_au_contrat(client):
    """Le fichier de démonstration contient 150 lignes valides et 3 erreurs volontaires."""
    import csv
    import io

    text = client.get("/console/exemple_profils.csv").text
    rows = list(csv.DictReader(io.StringIO(text)))
    report = client.post("/profiles/validate", json={"rows": rows}, headers=HEADERS).json()
    assert (report["valid_count"], report["invalid_count"]) == (150, 3)


def test_model_info_expose_les_libelles(client):
    labels = client.get("/model-info", headers=HEADERS).json()["feature_labels"]
    assert labels["avg_reaction_ms"] == "Temps de réaction moyen"
