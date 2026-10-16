"""Traçabilité des données d'entraînement — critère 3.5 du bloc 4 (reproductibilité).

Les données ne sont pas versionnées dans Git (volumineuses, et en production elles
contiendraient des données personnelles). À la place, chaque modèle enregistre la
"recette" de ses données d'entraînement : comment les reconstruire à l'identique.
L'empreinte (fingerprint) enregistrée à côté prouve que la reconstruction est exacte.

Deux formes de recette :
- {"generate": {...}} : données produites par le générateur (modèle v1) ;
- {"base": <recette du modèle précédent>, "recent": <source>, ...} : données d'un
  réentraînement = anciennes données + nouvelles fiches étiquetées, dans une fenêtre
  glissante des N lignes les plus récentes.

La recette s'emboîte : celle de v3 contient celle de v2, qui contient celle de v1.
C'est l'arbre généalogique complet des données de chaque modèle.
"""

from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from src.data.generate import generate_dataset
from src.train import data_fingerprint, split_by_player

# --- Scénarios de démonstration ("matchs récents" synthétiques) ------------------------
# Graine et dates différentes de l'entraînement : de NOUVEAUX joueurs, après août-septembre.
SCENARIOS = {
    "normal": {"cheat_intensity": 1.0, "game_patch": False},
    "patch": {"cheat_intensity": 1.0, "game_patch": True},
    "humanisee": {"cheat_intensity": 0.4, "game_patch": False},
}
SCENARIO_ROWS = 30_000  # le volume d'une journée environ
SCENARIO_SEED = 2026
SCENARIO_START = "2026-10-01"


def scenario_data(name: str) -> pd.DataFrame:
    """Crée les matchs "récents" d'un scénario de démonstration."""
    if name not in SCENARIOS:
        raise ValueError(f"Scénario inconnu : {name}. Choix : {', '.join(SCENARIOS)}")
    return generate_dataset(
        n_matches=SCENARIO_ROWS,
        seed=SCENARIO_SEED,
        start_date=SCENARIO_START,
        **SCENARIOS[name],
    )


# --- Sources et découpages --------------------------------------------------------------


def load_source(source: dict) -> pd.DataFrame:
    """Charge une source de données récentes décrite dans une recette.

    - {"scenario": "patch"} : scénario de démonstration ;
    - {"csv": "chemin.csv", "fingerprint": "..."} : export réel, vérifié par empreinte.
    """
    if "scenario" in source:
        return scenario_data(source["scenario"])
    df = pd.read_csv(Path(source["csv"]))
    if data_fingerprint(df) != source["fingerprint"]:
        raise RuntimeError(f"Le fichier {source['csv']} a changé depuis l'entraînement.")
    return df


def split_recent(
    recent: pd.DataFrame, seed: int, holdout_share: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sépare des fiches en deux parties, ``holdout_share`` étant la part de la seconde.

    La séparation se fait par joueur, comme pour le modèle v1 : un même joueur n'est
    jamais des deux côtés (sinon le modèle reconnaîtrait le joueur, pas la triche).
    """
    splitter = GroupShuffleSplit(n_splits=1, test_size=holdout_share, random_state=seed)
    train_idx, holdout_idx = next(splitter.split(recent, groups=recent["player_id"]))
    return recent.iloc[train_idx], recent.iloc[holdout_idx]


def old_pool_and_test(old: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sépare les anciennes données en "réutilisables" et "test", comme à l'entraînement.

    Le test de l'ancien modèle reste hors de l'entraînement du nouveau : on peut ainsi
    vérifier honnêtement que le nouveau n'a pas "oublié" les anciennes formes de triche.
    """
    train, val, test = split_by_player(old, seed)
    return pd.concat([train, val]), test


def training_window(old: pd.DataFrame, new: pd.DataFrame, window: int) -> pd.DataFrame:
    """Garde les ``window`` lignes les plus récentes (fenêtre glissante).

    Pourquoi : après une mise à jour du jeu, les vieilles données décrivent un jeu qui
    n'existe plus. La fenêtre fixe aussi la durée d'entraînement (toujours ~3 secondes),
    quelle que soit l'ancienneté du service.
    """
    combined = pd.concat([old, new], ignore_index=True)
    combined = combined.sort_values("match_date", kind="mergesort")  # tri stable
    return combined.tail(window).reset_index(drop=True)


# --- Reconstruction ---------------------------------------------------------------------


def recent_window(
    old_pool: pd.DataFrame, recent: pd.DataFrame, seed: int, train_share: float, window: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construit les données d'entraînement d'un réentraînement.

    Returns:
        (fenêtre d'entraînement, fiches récentes mises de côté pour le seuil et l'examen)

    Les fiches récentes font foi : si un joueur y apparaît, ses anciennes fiches sont
    retirées (une fiche réexportée remplace l'ancienne, et un joueur gardé pour l'examen
    ne doit jamais avoir été vu à l'entraînement).
    """
    recent_train, recent_rest = split_recent(recent, seed, 1 - train_share)
    old_pool = old_pool[~old_pool["player_id"].isin(recent["player_id"])]
    return training_window(old_pool, recent_train, window), recent_rest


def recipe_of(metadata: dict) -> dict:
    """Recette des données d'un modèle (les modèles v1 n'en ont pas : on la déduit)."""
    recipe = metadata["data"].get("recipe")
    if recipe is not None:
        return recipe
    return {"generate": {"n_matches": metadata["data"]["n_rows"], "seed": metadata["seed"]}}


def build_training_data(recipe: dict) -> pd.DataFrame:
    """Reconstruit exactement les données d'entraînement décrites par une recette."""
    if "generate" in recipe:
        return generate_dataset(**recipe["generate"])
    old = build_training_data(recipe["base"])
    old_pool, _ = old_pool_and_test(old, recipe["seed"])
    window, _ = recent_window(
        old_pool,
        load_source(recipe["recent"]),
        recipe["seed"],
        recipe["recent_train_share"],
        recipe["window"],
    )
    return window


def load_training_data(metadata: dict) -> pd.DataFrame:
    """Reconstruit les données d'entraînement d'un modèle et vérifie l'empreinte."""
    df = build_training_data(recipe_of(metadata))
    expected = metadata["data"]["fingerprint"]
    if data_fingerprint(df) != expected:
        raise RuntimeError(
            f"Données reconstruites différentes de celles de l'entraînement "
            f"(empreinte {data_fingerprint(df)} au lieu de {expected})."
        )
    return df
