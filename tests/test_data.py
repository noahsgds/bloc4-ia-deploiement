"""Tests des données : génération reproductible et contrôle du format."""

import pytest

from src.config import ALL_COLUMNS, TARGET
from src.data import DataValidationError, apply_game_patch, generate_dataset, validate_dataset


@pytest.fixture(scope="module")
def df():
    return generate_dataset(n_matches=6_000, seed=1)


def test_meme_graine_memes_donnees():
    assert generate_dataset(500, seed=3).equals(generate_dataset(500, seed=3))


def test_format_et_part_de_tricheurs(df):
    assert list(df.columns) == ALL_COLUMNS
    assert 0.01 < df[TARGET].mean() < 0.06  # environ 3 % de tricheurs
    validate_dataset(df)  # les données générées respectent le contrat


def test_les_tricheurs_ont_des_statistiques_plus_suspectes(df):
    means = df.groupby(TARGET)[["headshot_rate", "avg_reaction_ms"]].mean()
    assert means.loc[1, "headshot_rate"] > means.loc[0, "headshot_rate"]
    assert means.loc[1, "avg_reaction_ms"] < means.loc[0, "avg_reaction_ms"]


def test_le_patch_rend_tout_le_monde_plus_precis(df):
    assert apply_game_patch(df)["accuracy"].mean() > df["accuracy"].mean()


@pytest.mark.parametrize(
    "corruption, message",
    [
        (lambda d: d.drop(columns=["accuracy"]), "Colonnes manquantes"),
        (lambda d: d.assign(accuracy=1.5), "hors de"),
        (lambda d: d.assign(platform="xbox"), "inconnue"),
        (lambda d: d.assign(rank_tier=None), "manquante"),
        (
            lambda d: d.assign(match_id=d["match_id"].iloc[0], player_id=d["player_id"].iloc[0]),
            "doublon",
        ),
    ],
    ids=["colonne_manquante", "hors_bornes", "categorie_inconnue", "valeur_manquante", "doublons"],
)
def test_donnees_invalides_refusees_avec_un_message_clair(df, corruption, message):
    with pytest.raises(DataValidationError, match=message):
        validate_dataset(corruption(df.copy()))
