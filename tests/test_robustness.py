"""Tests de robustesse du modèle (critère 1.3 de la grille ; critère d'acceptation CA-02).

Question posée : le modèle reste-t-il fiable quand les données d'entrée sont
imparfaites (valeurs manquantes, aberrantes, catégories inconnues, bruit de mesure) ?

Deux niveaux d'exigence :
1. Ne jamais planter : toute entrée de la bonne forme donne une probabilité entre 0 et 1.
2. Se dégrader doucement : une perturbation réaliste ne doit pas effondrer la performance.

Lancer : pytest tests/test_robustness.py -v
"""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from src.config import FEATURES, NUMERIC_FEATURES, TARGET
from src.data.generate import generate_dataset
from src.train import split_by_player, train_and_select


@pytest.fixture(scope="module")
def setup():
    """Modèle entraîné une fois + jeu de test (jamais vu à l'entraînement)."""
    df = generate_dataset(n_matches=50_000, seed=42)
    result = train_and_select(df, seed=42)
    _, _, test = split_by_player(df, seed=42)
    return result.model, test.reset_index(drop=True)


def scores_of(model, X: pd.DataFrame) -> np.ndarray:
    """Probabilité de triche pour chaque ligne."""
    return model.predict_proba(X[FEATURES])[:, 1]


def assert_valid_probabilities(scores: np.ndarray) -> None:
    assert np.all(np.isfinite(scores)), "le modèle a produit des valeurs non finies"
    assert np.all((scores >= 0) & (scores <= 1)), "probabilités hors de [0, 1]"


# --- 1. Ne jamais planter -------------------------------------------------------------


@pytest.mark.parametrize("column", NUMERIC_FEATURES)
def test_valeur_manquante_sur_n_importe_quelle_variable(setup, column):
    """Même hors contrat (une seule colonne est censée pouvoir manquer), pas de plantage."""
    model, test = setup
    X = test.head(100).copy()
    X[column] = np.nan
    assert_valid_probabilities(scores_of(model, X))


def test_toutes_les_valeurs_manquantes(setup):
    model, test = setup
    X = test.head(20).copy()
    X[NUMERIC_FEATURES] = np.nan
    assert_valid_probabilities(scores_of(model, X))


def test_categorie_inconnue(setup):
    """Une nouvelle plateforme (ex. 'cloud') est ignorée au lieu de faire planter."""
    model, test = setup
    X = test.head(100).copy()
    X["platform"] = "cloud"
    X["input_device"] = "ecran_tactile"
    assert_valid_probabilities(scores_of(model, X))


def test_valeurs_aberrantes(setup):
    """Valeurs absurdes (précision de 500 %, réaction de 1 ms) : pas de plantage."""
    model, test = setup
    X = test.head(100).copy()
    X["accuracy"] = 5.0
    X["avg_reaction_ms"] = 1.0
    X["kd_ratio"] = 1e6
    X["hours_played_total"] = -10
    assert_valid_probabilities(scores_of(model, X))


def test_ordre_des_colonnes_sans_effet(setup):
    """Le modèle utilise les noms de colonnes, pas leur position."""
    model, test = setup
    X = test.head(200)
    shuffled = X[list(reversed(FEATURES))]
    np.testing.assert_allclose(scores_of(model, X), model.predict_proba(shuffled)[:, 1])


def test_prediction_unitaire_identique_au_lot(setup):
    """Scorer une fiche seule ou dans un lot donne exactement le même résultat."""
    model, test = setup
    X = test.head(20)
    batch = scores_of(model, X)
    one_by_one = [scores_of(model, X.iloc[[i]])[0] for i in range(len(X))]
    np.testing.assert_allclose(batch, one_by_one)


# --- 2. Se dégrader doucement ---------------------------------------------------------


def pr_auc(model, X: pd.DataFrame) -> float:
    return average_precision_score(X[TARGET], scores_of(model, X))


def test_bruit_de_mesure_leger(setup):
    """Un bruit de 5 % de l'écart-type sur chaque mesure ne change presque pas les DÉCISIONS.

    On juge la stabilité sur ce qui compte pour les modérateurs (le classement et les
    signalements), pas sur la valeur exacte du score : le modèle est entraîné avec des
    poids "balanced", ses scores sont donc étirés et bougent de quelques points sans que
    l'ordre des joueurs ne change.
    """
    model, test = setup
    rng = np.random.default_rng(0)
    noisy = test.copy()
    for column in NUMERIC_FEATURES:
        std = test[column].std()
        noisy[column] = test[column] + rng.normal(0, 0.05 * std, len(test))

    original, perturbed = scores_of(model, test), scores_of(model, noisy)
    top_original = set(np.argsort(-original)[:100])
    top_perturbed = set(np.argsort(-perturbed)[:100])
    assert len(top_original & top_perturbed) >= 90, "le top 100 de la file de revue change trop"
    assert pr_auc(model, noisy) > pr_auc(model, test) - 0.05


def test_perte_de_telemetrie_massive(setup):
    """Si 30 % des temps de réaction sont perdus (panne), la PR-AUC baisse peu."""
    model, test = setup
    rng = np.random.default_rng(1)
    degraded = test.copy()
    lost = rng.random(len(test)) < 0.30
    degraded.loc[lost, "avg_reaction_ms"] = np.nan
    assert pr_auc(model, degraded) > pr_auc(model, test) - 0.08


def test_signalements_indisponibles(setup):
    """Si le système de signalement tombe en panne (0 partout), le modèle reste utile.

    Garantit que le modèle ne dépend pas d'une seule variable : il doit rester nettement
    meilleur que le hasard (PR-AUC du hasard = part de tricheurs, environ 0,03).
    """
    model, test = setup
    no_reports = test.assign(reports_received=0)
    assert pr_auc(model, no_reports) > 5 * test[TARGET].mean()
