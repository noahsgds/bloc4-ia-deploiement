"""Préparation des variables (preprocessing) avant le modèle.

Le preprocessing est intégré au modèle dans un même "Pipeline" scikit-learn :
les mêmes transformations sont appliquées à l'entraînement ET en production
(dans l'API), sans risque d'oubli ou d'écart entre les deux.
"""

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def build_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    """Construit la transformation des colonnes.

    - Numériques : les valeurs manquantes (perte de télémétrie) sont remplacées par la
      médiane apprise sur les données d'entraînement. Optionnellement, mise à l'échelle
      (moyenne 0, écart-type 1), utile pour la régression logistique, inutile pour les arbres.
    - Catégorielles : encodage "one-hot" (une colonne 0/1 par valeur). Une valeur inconnue
      en production est ignorée au lieu de faire planter la prédiction (robustesse).

    Args:
        scale_numeric: True pour standardiser les variables numériques.
    """
    numeric_steps = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    return ColumnTransformer(
        transformers=[
            ("num", Pipeline(numeric_steps), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
