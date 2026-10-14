"""Tests du modèle : performance, comparaison à la règle actuelle, sauvegarde, reproductibilité.

Le modèle est entraîné une seule fois (fixture de module) pour que les tests restent
rapides. On utilise 50 000 lignes : en dessous, le jeu de test contient trop peu de
tricheurs et les métriques deviennent instables.

Lancer : pytest tests/test_model.py -v
"""

import numpy as np
import pytest

from src.config import ACCEPTANCE_THRESHOLDS, FEATURES, MAX_FALSE_POSITIVE_RATE, TARGET
from src.data.generate import generate_dataset
from src.evaluate import precision_at_top, threshold_for_max_fpr
from src.train import load_champion, save_model, split_by_player, train_and_select


@pytest.fixture(scope="module")
def data():
    return generate_dataset(n_matches=50_000, seed=42)


@pytest.fixture(scope="module")
def result(data):
    return train_and_select(data, seed=42)


# --- Performance (CA-01, critère 1.2) ------------------------------------------


@pytest.mark.parametrize("metric", list(ACCEPTANCE_THRESHOLDS))
def test_seuils_du_cahier_des_charges_atteints(result, metric):
    assert result.test_metrics[metric] >= ACCEPTANCE_THRESHOLDS[metric], (
        f"{metric} = {result.test_metrics[metric]} < seuil {ACCEPTANCE_THRESHOLDS[metric]}"
    )


def test_faux_positifs_maitrises(result):
    # Seuil fixé sur la validation : on tolère un léger dépassement sur le test.
    assert result.test_metrics["false_positive_rate"] <= MAX_FALSE_POSITIVE_RATE * 1.5


def test_bat_la_regle_des_signalements(result):
    model, baseline = result.test_metrics, result.baseline_test_metrics
    assert model["pr_auc"] > 2 * baseline["pr_auc"]
    assert model["precision_top"] > baseline["precision_top"]


# --- Méthodologie ----------------------------------------------------------------


def test_aucun_joueur_dans_deux_jeux_a_la_fois(data):
    """Pas de fuite de données : un joueur est entièrement dans train, validation OU test."""
    train, val, test = split_by_player(data, seed=42)
    train_ids, val_ids, test_ids = (set(d["player_id"]) for d in (train, val, test))
    assert not train_ids & val_ids
    assert not train_ids & test_ids
    assert not val_ids & test_ids
    assert len(train) + len(val) + len(test) == len(data)


def test_entrainement_reproductible():
    """Même données + même graine -> mêmes métriques (critère 3.5)."""
    df = generate_dataset(n_matches=8_000, seed=7)
    first = train_and_select(df, seed=7).test_metrics
    second = train_and_select(df, seed=7).test_metrics
    assert first == second


def test_probabilites_entre_0_et_1(result, data):
    scores = result.model.predict_proba(data[FEATURES].head(200))[:, 1]
    assert np.all((scores >= 0) & (scores <= 1))


# --- Fonctions d'évaluation ------------------------------------------------------


def test_precision_at_top():
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    scores = np.array([0.9, 0.8, 0.7, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert precision_at_top(y, scores, share=0.2) == 0.5  # top 2 : un tricheur sur deux


def test_seuil_respecte_le_plafond_de_faux_positifs():
    rng = np.random.default_rng(0)
    y = (rng.random(5_000) < 0.05).astype(int)
    scores = rng.random(5_000) + 0.5 * y
    threshold = threshold_for_max_fpr(y, scores, max_fpr=0.01)
    fpr = np.mean(scores[y == 0] >= threshold)
    assert fpr <= 0.01


# --- Sauvegarde et chargement ------------------------------------------------------


def test_sauvegarde_et_rechargement(result, data, tmp_path):
    save_model(result, version="test", seed=42, models_dir=tmp_path)
    model, metadata = load_champion(models_dir=tmp_path)

    assert metadata["version"] == "test"
    assert metadata["threshold"] == result.threshold
    assert "fingerprint" in metadata["data"]
    sample = data[FEATURES].head(50)
    np.testing.assert_allclose(
        model.predict_proba(sample)[:, 1], result.model.predict_proba(sample)[:, 1]
    )


def test_erreur_claire_si_aucun_modele(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m src.train"):
        load_champion(models_dir=tmp_path)


def test_cible_bien_presente(data):
    assert set(data[TARGET].unique()) == {0, 1}
