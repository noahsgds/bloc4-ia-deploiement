"""Tests du réentraînement automatique et de la promotion contrôlée (étape 10)."""

import json
import shutil

import numpy as np
import pandas as pd
import pytest

from retrain.retrain import (
    bootstrap_gain_share,
    meets_specification,
    next_version,
    promotion_decision,
    retrain,
)
from src.config import MODELS_DIR, TARGET
from src.data.validate import DataValidationError
from src.lineage import (
    load_training_data,
    recent_window,
    recipe_of,
    scenario_data,
    training_window,
)
from src.train import load_champion, set_champion


def model_eval(pr_auc=0.55, fpr=0.01, old_pr_auc=0.58, old_fpr=0.01, fairness_ok=True):
    return {
        "recent": {"pr_auc": pr_auc, "false_positive_rate": fpr},
        "old": {"pr_auc": old_pr_auc, "false_positive_rate": old_fpr},
        "fairness_ok": fairness_ok,
    }


CHAMPION = model_eval()


# --- Règles de promotion ----------------------------------------------------------------


def test_promu_si_le_gain_est_confirme():
    decision = promotion_decision(CHAMPION, model_eval(pr_auc=0.60), gain_share=0.99)
    assert decision["promote"] is True


def test_refuse_si_le_gain_peut_etre_du_au_hasard():
    decision = promotion_decision(CHAMPION, model_eval(pr_auc=0.56), gain_share=0.70)
    assert decision["promote"] is False
    assert decision["checks"]["apporte_un_gain"] is False


def test_promu_s_il_corrige_les_faux_positifs_meme_avec_une_petite_perte():
    champion = model_eval(fpr=0.05)  # le champion accuse 5 % d'innocents
    decision = promotion_decision(champion, model_eval(pr_auc=0.53), gain_share=0.20)
    assert decision["promote"] is True


def test_refuse_s_il_accuse_trop_d_innocents():
    decision = promotion_decision(CHAMPION, model_eval(pr_auc=0.60, fpr=0.02), gain_share=0.99)
    assert decision["checks"]["faux_positifs_recents"] is False
    assert decision["promote"] is False


def test_refuse_s_il_oublie_les_anciennes_triches():
    decision = promotion_decision(
        CHAMPION, model_eval(pr_auc=0.60, old_pr_auc=0.50), gain_share=0.99
    )
    assert decision["checks"]["pas_d_oubli"] is False
    assert decision["promote"] is False


def test_refuse_s_il_n_est_pas_equitable():
    decision = promotion_decision(
        CHAMPION, model_eval(pr_auc=0.60, fairness_ok=False), gain_share=0.99
    )
    assert decision["promote"] is False


def test_les_raisons_sont_lisibles():
    decision = promotion_decision(CHAMPION, model_eval(pr_auc=0.56), gain_share=0.70)
    assert len(decision["reasons"]) == len(decision["checks"])
    assert decision["reasons"][0].startswith("NON")


def test_seuils_du_cahier_des_charges():
    good = {"roc_auc": 0.87, "pr_auc": 0.59, "precision_top": 0.94, "recall": 0.57}
    assert meets_specification(good) is True
    assert meets_specification(good | {"pr_auc": 0.20}) is False


# --- Outils -----------------------------------------------------------------------------


def test_bootstrap_challenger_parfait_contre_hasard():
    rng = np.random.default_rng(0)
    y = np.array([1] * 30 + [0] * 270)
    players = np.repeat(np.arange(100), 3)
    perfect = y + rng.random(300) * 0.1
    random_scores = rng.random(300)
    assert bootstrap_gain_share(y, random_scores, perfect, players, seed=1, draws=50) == 1.0
    assert bootstrap_gain_share(y, perfect, perfect, players, seed=1, draws=50) == 0.0


def test_numero_de_version_suivant(tmp_path):
    assert next_version(tmp_path) == "v1"
    for name in ["cheat_model_v1.json", "cheat_model_v3.json", "cheat_model_vX.json"]:
        (tmp_path / name).write_text("{}")
    assert next_version(tmp_path) == "v4"


def test_fenetre_glissante_garde_les_lignes_les_plus_recentes():
    old = pd.DataFrame({"match_date": ["2026-08-01", "2026-08-02"], "n": [1, 2]})
    new = pd.DataFrame({"match_date": ["2026-10-01"], "n": [3]})
    window = training_window(old, new, window=2)
    assert window["n"].tolist() == [2, 3]


def test_les_fiches_recentes_font_foi_et_aucun_joueur_examine_n_est_appris():
    recent = scenario_data("normal").head(3000)
    old = scenario_data("normal").iloc[2000:6000]  # 1000 lignes en commun
    window, rest = recent_window(old, recent, seed=42, train_share=0.5, window=50_000)
    assert not set(rest["player_id"]) & set(window["player_id"])
    assert not window.duplicated(["player_id", "match_id"]).any()


def test_recette_du_modele_v1_reconstruit_les_memes_donnees():
    metadata = json.loads((MODELS_DIR / "cheat_model_v1.json").read_text())
    assert recipe_of(metadata) == {"generate": {"n_matches": 50_000, "seed": 42}}
    load_training_data(metadata)  # lève une erreur si l'empreinte diffère


def test_retour_arriere(tmp_path):
    for f in MODELS_DIR.iterdir():
        shutil.copy(f, tmp_path)
    with pytest.raises(FileNotFoundError):
        set_champion("v99", tmp_path)
    set_champion("v1", tmp_path)
    assert json.loads((tmp_path / "champion.json").read_text()) == {"version": "v1"}


# --- Gestion des données récentes -------------------------------------------------------


@pytest.fixture
def models_copy(tmp_path):
    """Copie du modèle v1 en production : point de départ fixe des scénarios, même si
    un modèle plus récent a été promu depuis dans le dépôt."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    for f in MODELS_DIR.glob("cheat_model_v1.*"):
        shutil.copy(f, models_dir)
    set_champion("v1", models_dir)
    return models_dir


def test_format_de_donnees_modifie_arrete_le_reentrainement(models_copy, tmp_path):
    recent = scenario_data("normal").drop(columns=["accuracy"])
    with pytest.raises(DataValidationError):
        retrain(recent, {"scenario": "x"}, models_copy, tmp_path / "rapports")


def test_fiches_sans_etiquette_refusees(models_copy, tmp_path):
    recent = scenario_data("normal")
    recent[TARGET] = recent[TARGET].astype(float)
    recent.loc[recent.index[:10], TARGET] = np.nan
    with pytest.raises((ValueError, DataValidationError)):
        retrain(recent, {"scenario": "x"}, models_copy, tmp_path / "rapports")


# --- Scénarios de bout en bout ----------------------------------------------------------


def test_apres_un_patch_le_challenger_est_promu_et_tracable(models_copy, tmp_path):
    report = retrain(
        scenario_data("patch"), {"scenario": "patch"}, models_copy, tmp_path / "rapports"
    )
    assert report["promoted"] is True
    # Le champion accusait trop d'innocents, le challenger corrige.
    assert report["champion"]["recent"]["false_positive_rate"] > 0.03
    assert report["challenger"]["recent"]["false_positive_rate"] <= 0.015

    _, metadata = load_champion(models_copy)
    assert metadata["version"] == "v2"
    assert metadata["parent_version"] == "v1"
    assert metadata["acceptance"]["passed"] is True
    load_training_data(metadata)  # la recette de v2 reconstruit exactement ses données
    assert (tmp_path / "rapports" / "reentrainement_v2.json").exists()

    set_champion("v1", models_copy)  # retour arrière toujours possible
    assert load_champion(models_copy)[1]["version"] == "v1"


def test_triche_humanisee_mieux_mais_insuffisant(models_copy, tmp_path):
    report = retrain(
        scenario_data("humanisee"),
        {"scenario": "humanisee"},
        models_copy,
        tmp_path / "rapports",
        dry_run=True,
    )
    assert report["decision"]["promote"] is True
    assert report["meets_specification"] is False  # il faut de nouvelles variables
    assert report["promoted"] is False  # simulation : rien n'est enregistré
    assert not (models_copy / "cheat_model_v2.joblib").exists()
