"""Tests du générateur de données et de la validation du contrat.

Lancer : pytest tests/test_data.py -v
"""

import numpy as np
import pandas as pd
import pytest

from src.config import ALL_COLUMNS, TARGET
from src.data.generate import generate_dataset
from src.data.validate import DataValidationError, validate_dataset


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    """Un petit jeu de données réutilisé par plusieurs tests (généré une seule fois)."""
    return generate_dataset(n_matches=5_000, seed=42)


# --- Générateur ---------------------------------------------------------------


def test_colonnes_conformes_au_contrat(dataset):
    assert list(dataset.columns) == ALL_COLUMNS


def test_meme_graine_memes_donnees():
    """Reproductibilité (critère 3.5) : même graine -> données identiques."""
    df1 = generate_dataset(n_matches=500, seed=123)
    df2 = generate_dataset(n_matches=500, seed=123)
    pd.testing.assert_frame_equal(df1, df2)


def test_graines_differentes_donnees_differentes():
    df1 = generate_dataset(n_matches=500, seed=1)
    df2 = generate_dataset(n_matches=500, seed=2)
    assert not df1.equals(df2)


def test_taux_de_tricheurs_environ_3_pourcents(dataset):
    assert 0.01 < dataset[TARGET].mean() < 0.06


def test_les_tricheurs_ont_des_stats_anormales(dataset):
    """Le signal existe : un tricheur réagit plus vite et vise mieux la tête en moyenne."""
    honest = dataset[dataset[TARGET] == 0]
    cheaters = dataset[dataset[TARGET] == 1]
    assert cheaters["headshot_rate"].mean() > honest["headshot_rate"].mean()
    assert cheaters["avg_reaction_ms"].mean() < honest["avg_reaction_ms"].mean()


def test_triche_humanisee_plus_difficile_a_detecter():
    """Drift : avec une triche "humanisée", l'écart tricheurs / honnêtes se réduit."""

    def headshot_gap(df: pd.DataFrame) -> float:
        return (
            df.loc[df[TARGET] == 1, "headshot_rate"].mean()
            - df.loc[df[TARGET] == 0, "headshot_rate"].mean()
        )

    classic = generate_dataset(n_matches=5_000, seed=42, cheat_intensity=1.0)
    humanized = generate_dataset(n_matches=5_000, seed=42, cheat_intensity=0.4)
    assert headshot_gap(humanized) < headshot_gap(classic)


def test_valeurs_manquantes_seulement_sur_le_temps_de_reaction(dataset):
    columns_with_missing = set(dataset.columns[dataset.isna().any()])
    assert columns_with_missing <= {"avg_reaction_ms"}


def test_parametres_invalides_refuses():
    with pytest.raises(ValueError):
        generate_dataset(n_matches=0)
    with pytest.raises(ValueError):
        generate_dataset(n_matches=100, cheat_intensity=1.5)


# --- Validation du contrat ----------------------------------------------------


def test_donnees_generees_valides(dataset):
    validate_dataset(dataset)  # ne doit lever aucune erreur


def test_colonne_manquante_detectee(dataset):
    with pytest.raises(DataValidationError, match="Colonnes manquantes"):
        validate_dataset(dataset.drop(columns=["accuracy"]))


def test_valeur_hors_bornes_detectee(dataset):
    corrupted = dataset.copy()
    corrupted.loc[0, "accuracy"] = 1.7  # une précision de 170 % est impossible
    with pytest.raises(DataValidationError, match="accuracy"):
        validate_dataset(corrupted)


def test_categorie_inconnue_detectee(dataset):
    corrupted = dataset.copy()
    corrupted.loc[0, "platform"] = "mobile"
    with pytest.raises(DataValidationError, match="platform"):
        validate_dataset(corrupted)


def test_valeur_manquante_interdite_detectee(dataset):
    corrupted = dataset.copy()
    corrupted.loc[0, "rank_tier"] = np.nan
    with pytest.raises(DataValidationError, match="rank_tier"):
        validate_dataset(corrupted)


def test_changement_de_type_detecte(dataset):
    """Format modifié (critère 3.3) : une colonne numérique reçue en texte est refusée."""
    corrupted = dataset.copy()
    corrupted["kd_ratio"] = corrupted["kd_ratio"].astype(str)
    with pytest.raises(DataValidationError, match="kd_ratio"):
        validate_dataset(corrupted)
