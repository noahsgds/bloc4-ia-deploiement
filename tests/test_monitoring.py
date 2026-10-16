"""Tests de la surveillance du modèle (étape 9).

- Les règles de décision (seuils d'alerte) sont testées sans Evidently : rapides.
- Les trois scénarios de bout en bout utilisent Evidently ; ils sont ignorés si la
  bibliothèque n'est pas installée et s'exécutent dans la CI GitHub.
"""

import json
import os

import pytest

from monitoring.drift_report import (
    data_drift_status,
    overall_status,
    performance_status,
    scenario_data,
)
from src.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES

REFERENCE = {"pr_auc": 0.59, "false_positive_rate": 0.013, "recall": 0.57}
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def current(pr_auc=0.58, fpr=0.01):
    return {"pr_auc": pr_auc, "false_positive_rate": fpr, "recall": 0.55}


# --- Dérive des données -----------------------------------------------------------------


def test_aucune_derive_si_toutes_les_distances_sont_faibles():
    status = data_drift_status({c: 0.02 for c in FEATURES})
    assert status["drifted_columns"] == []
    assert status["alert"] is False


def test_une_seule_variable_qui_derive_ne_declenche_pas_d_alerte():
    scores = {c: 0.02 for c in FEATURES} | {"accuracy": 0.5}
    status = data_drift_status(scores)
    assert status["drifted_columns"] == ["accuracy"]
    assert status["alert"] is False  # 1 variable sur 13 : en dessous de 25 %


def test_alerte_si_un_quart_des_variables_derive():
    drifting = ["accuracy", "headshot_rate", "avg_reaction_ms", "kills_per_min"]
    scores = {c: 0.02 for c in FEATURES} | {c: 0.3 for c in drifting}
    status = data_drift_status(scores)
    assert status["drifted_columns"] == sorted(drifting)
    assert status["alert"] is True


# --- Dérive de performance --------------------------------------------------------------


def test_performance_stable_pas_d_alerte():
    assert performance_status(current(), REFERENCE)["alert"] is False


def test_alerte_si_la_pr_auc_s_effondre():
    status = performance_status(current(pr_auc=0.15), REFERENCE)
    assert status["alert"] is True
    assert "PR-AUC" in status["reasons"][0]


def test_alerte_si_trop_de_joueurs_honnetes_sont_signales():
    status = performance_status(current(fpr=0.05), REFERENCE)
    assert status["alert"] is True
    assert "honnêtes" in status["reasons"][0]


def test_statut_global_regroupe_les_raisons():
    drift = data_drift_status({c: 0.3 for c in FEATURES})
    perf = performance_status(current(pr_auc=0.1), REFERENCE)
    status = overall_status(drift, perf)
    assert status["status"] == "alerte"
    assert len(status["reasons"]) == 2
    assert overall_status(data_drift_status({c: 0.0 for c in FEATURES}), None) == {
        "status": "ok",
        "reasons": [],
    }


def test_scenario_inconnu_refuse():
    with pytest.raises(ValueError):
        scenario_data("inexistant")


# --- Scénarios de bout en bout (Evidently) ----------------------------------------------


@pytest.fixture(scope="module")
def run_scenario(tmp_path_factory):
    if os.getenv("CI"):
        import evidently  # noqa: F401  (dans la CI GitHub, ces tests ne doivent jamais être ignorés)
    else:
        pytest.importorskip("evidently")
    from monitoring.drift_report import build_report

    reports_dir = tmp_path_factory.mktemp("rapports")

    def _run(name):
        return build_report(scenario_data(name), name, reports_dir=reports_dir), reports_dir

    return _run


def test_scenario_normal_sans_alerte(run_scenario):
    summary, reports_dir = run_scenario("normal")
    assert summary["status"] == "ok", summary["reasons"]
    assert (reports_dir / summary["html_report"]).exists()
    saved = json.loads((reports_dir / "dernier_resume.json").read_text())
    assert saved["status"] == "ok"


def test_scenario_patch_derive_des_donnees_et_faux_positifs(run_scenario):
    summary, _ = run_scenario("patch")
    assert summary["status"] == "alerte"
    assert summary["data_drift"]["alert"] is True
    assert "accuracy" in summary["data_drift"]["drifted_columns"]
    assert summary["performance"]["current"]["false_positive_rate"] > 0.02


def test_scenario_triche_humanisee_invisible_sans_verite_terrain(run_scenario):
    """Le cas qui justifie la surveillance de performance : les données ne bougent pas,
    mais le modèle ne voit plus les tricheurs."""
    summary, _ = run_scenario("humanisee")
    assert summary["data_drift"]["alert"] is False
    assert summary["performance"]["alert"] is True
    assert summary["status"] == "alerte"
