"""Tests de la surveillance et du réentraînement.

Les scénarios avec Evidently sont ignorés si la bibliothèque manque en local, mais sont
obligatoires dans la CI GitHub (variable CI définie).
"""

import os
import shutil

import pytest

from monitoring.monitor import decide, monitor
from monitoring.retrain import retrain
from src.config import CATEGORICAL_FEATURES, MODELS_DIR, NUMERIC_FEATURES
from src.data import scenario_data
from src.model import load_champion

COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
REFERENCE = {"pr_auc": 0.59, "false_positive_rate": 0.013}


def test_pas_d_alerte_si_rien_ne_change():
    result = decide(
        {c: 0.02 for c in COLUMNS}, {"pr_auc": 0.58, "false_positive_rate": 0.01}, REFERENCE
    )
    assert result["status"] == "ok"


def test_alerte_si_un_quart_des_variables_derive():
    distances = {c: 0.02 for c in COLUMNS} | {c: 0.3 for c in COLUMNS[:4]}
    assert decide(distances, None, REFERENCE)["status"] == "alerte"


def test_alerte_si_la_performance_baisse_ou_les_faux_positifs_montent():
    calm = {c: 0.02 for c in COLUMNS}
    assert (
        decide(calm, {"pr_auc": 0.15, "false_positive_rate": 0.01}, REFERENCE)["status"] == "alerte"
    )
    assert (
        decide(calm, {"pr_auc": 0.58, "false_positive_rate": 0.05}, REFERENCE)["status"] == "alerte"
    )


@pytest.fixture
def models_v1(tmp_path):
    """Copie du modèle v1 : point de départ fixe, même si une v2 a été promue depuis."""
    target = tmp_path / "models"
    target.mkdir()
    for f in MODELS_DIR.glob("*_v1.*"):
        shutil.copy(f, target)
    (target / "champion.json").write_text('{"version": "v1"}')
    return target


def test_apres_un_patch_le_nouveau_modele_est_promu(models_v1):
    report = retrain(scenario_data("patch"), models_v1)
    assert report["champion"]["false_positive_rate"] > 0.03  # l'ancien accuse des innocents
    assert report["promote"] and report["new_version"] == "v2"
    _, meta = load_champion(models_v1)
    assert meta["version"] == "v2" and meta["parent_version"] == "v1"


def test_sans_changement_on_garde_le_modele_actuel(models_v1):
    report = retrain(scenario_data("normal"), models_v1)
    assert not report["promote"]
    assert load_champion(models_v1)[1]["version"] == "v1"


@pytest.fixture
def evidently():
    if os.getenv("CI"):
        import evidently  # noqa: F401  (obligatoire dans la CI)
    else:
        pytest.importorskip("evidently")


@pytest.mark.parametrize(
    "scenario, status, drift",
    [("normal", "ok", False), ("patch", "alerte", True), ("humanisee", "alerte", False)],
)
def test_scenarios_de_surveillance(evidently, models_v1, tmp_path, scenario, status, drift):
    summary = monitor(scenario_data(scenario), scenario, models_v1, tmp_path)
    assert summary["status"] == status, summary["reasons"]
    assert (len(summary["drifted"]) >= 4) == drift  # la triche humanisée ne se voit pas
    assert (tmp_path / f"derive_{scenario}.html").exists()
