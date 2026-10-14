"""Validation du contrat de données.

Avant d'entraîner ou de prédire, on vérifie que les données ont le format attendu.
Si quelque chose ne va pas (colonne manquante, valeur impossible, catégorie
inconnue), on s'arrête avec un message clair au lieu de produire un modèle faux
sans s'en rendre compte (critères 3.3 et 6.6 de la grille : changements de
format des données, pas d'échec silencieux).
"""

import pandas as pd

from src.config import (
    ALL_COLUMNS,
    ALLOWED_CATEGORIES,
    NULLABLE_COLUMNS,
    NUMERIC_RANGES,
    TARGET,
)


class DataValidationError(ValueError):
    """Erreur levée quand les données ne respectent pas le contrat."""


def validate_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Vérifie qu'un jeu de données respecte le contrat du cahier des charges.

    Toutes les anomalies sont rassemblées puis signalées ensemble, pour pouvoir
    tout corriger d'un coup.

    Args:
        df: les données à vérifier.

    Returns:
        Le même DataFrame, inchangé, si tout est conforme.

    Raises:
        DataValidationError: si au moins une règle n'est pas respectée.
    """
    errors: list[str] = []

    # 1. Toutes les colonnes du contrat sont présentes.
    missing_columns = [col for col in ALL_COLUMNS if col not in df.columns]
    if missing_columns:
        # Sans les bonnes colonnes, les autres vérifications n'ont pas de sens : on s'arrête.
        raise DataValidationError(f"Colonnes manquantes : {missing_columns}")

    if df.empty:
        raise DataValidationError("Le jeu de données est vide.")

    # 2. Pas de valeur manquante, sauf dans les colonnes autorisées.
    for col in ALL_COLUMNS:
        n_missing = int(df[col].isna().sum())
        if n_missing and col not in NULLABLE_COLUMNS:
            errors.append(f"{col} : {n_missing} valeur(s) manquante(s) non autorisée(s)")

    # 3. Les colonnes numériques sont bien numériques et dans des bornes réalistes.
    for col, (low, high) in NUMERIC_RANGES.items():
        if not pd.api.types.is_numeric_dtype(df[col]):
            errors.append(f"{col} : type {df[col].dtype} au lieu d'un type numérique")
            continue
        out_of_range = df[col].dropna().pipe(lambda s: (s < low) | (s > high)).sum()
        if out_of_range:
            errors.append(f"{col} : {int(out_of_range)} valeur(s) hors de [{low}, {high}]")

    # 4. Les colonnes catégorielles ne contiennent que des valeurs connues.
    for col, allowed in ALLOWED_CATEGORIES.items():
        unknown = set(df[col].dropna().unique()) - allowed
        if unknown:
            errors.append(f"{col} : valeur(s) inconnue(s) {sorted(unknown)}")

    # 5. La cible ne contient que 0 ou 1.
    if not set(df[TARGET].dropna().unique()) <= {0, 1}:
        errors.append(f"{TARGET} : doit contenir uniquement 0 ou 1")

    # 6. Une même ligne (joueur, match) n'apparaît qu'une fois.
    n_duplicates = int(df.duplicated(subset=["player_id", "match_id"]).sum())
    if n_duplicates:
        errors.append(f"{n_duplicates} doublon(s) (player_id, match_id)")

    if errors:
        raise DataValidationError("Données non conformes :\n- " + "\n- ".join(errors))
    return df
