"""Explicabilité des prédictions (critères 1.5 et 5.5 ; exigence F3 du cahier des charges).

Pour chaque fiche (joueur, match), on indique les facteurs qui ont le plus pesé dans le
score, en phrases compréhensibles par un modérateur, par exemple :

    « Temps de réaction moyen : 112 ms (joueurs honnêtes de son rang : 262 ms)
      — augmente le risque »

Méthode : valeurs de SHAP (SHapley Additive exPlanations). Pour une prédiction, SHAP
répartit l'écart entre le score du joueur et le score moyen entre les variables, comme
on répartirait équitablement un gain entre les membres d'une équipe. Une contribution
positive pousse vers "tricheur", une contribution négative vers "honnête", et la somme
des contributions + la valeur de base redonne exactement le score du modèle.

Organisation du module :
- les fonctions de mise en forme (format_value, build_reason, top_reasons) ne dépendent
  pas de SHAP et sont testées partout ;
- compute_contributions est la seule fonction qui appelle SHAP.
"""

import math

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from src.config import CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES

# Libellé en français et format d'affichage de chaque variable.
# Formats : "pct" = pourcentage, "int" = entier, "dec" = 2 décimales.
FEATURE_LABELS = {
    "accuracy": ("Précision des tirs", "pct", ""),
    "headshot_rate": ("Taux de tirs à la tête", "pct", ""),
    "kd_ratio": ("Ratio éliminations / morts", "dec", ""),
    "kills_per_min": ("Éliminations par minute", "dec", ""),
    "damage_per_round": ("Dégâts par manche", "int", ""),
    "avg_reaction_ms": ("Temps de réaction moyen", "int", " ms"),
    "kills_through_smoke_ratio": ("Éliminations à travers la fumée", "pct", ""),
    "rank_tier": ("Rang", "int", ""),
    "account_age_days": ("Ancienneté du compte", "int", " jours"),
    "hours_played_total": ("Heures de jeu", "int", " h"),
    "reports_received": ("Signalements reçus", "int", ""),
    "input_device": ("Périphérique", "cat", ""),
    "platform": ("Plateforme", "cat", ""),
}

CATEGORY_LABELS = {
    "manette": "manette",
    "clavier_souris": "clavier-souris",
    "pc": "PC",
    "console": "console",
}


def format_value(feature: str, value) -> str:
    """Met une valeur en forme pour un humain (pourcentage, unité, libellé de catégorie)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "non mesuré"
    _, kind, unit = FEATURE_LABELS[feature]
    if kind == "cat":
        return CATEGORY_LABELS.get(str(value), str(value))
    if kind == "pct":
        return f"{float(value) * 100:.0f} %"
    if kind == "dec":
        return f"{float(value):.2f}"
    return f"{float(value):.0f}{unit}"


def build_reason(feature: str, value, contribution: float, reference: float | None) -> dict:
    """Construit une raison lisible à partir d'une contribution SHAP.

    Args:
        feature: nom technique de la variable.
        value: valeur observée pour ce joueur sur ce match.
        contribution: contribution SHAP (> 0 : augmente le risque de triche).
        reference: médiane des joueurs honnêtes du même rang (None pour les catégories).
    """
    label = FEATURE_LABELS[feature][0]
    direction = "augmente le risque" if contribution > 0 else "diminue le risque"
    text = f"{label} : {format_value(feature, value)}"
    if reference is not None:
        text += f" (joueurs honnêtes de son rang : {format_value(feature, reference)})"
    text += f" — {direction}"
    return {
        "feature": feature,
        "label": label,
        "value": None if pd.isna(value) else value,
        "reference": reference,
        "contribution": round(float(contribution), 4),
        "direction": "hausse" if contribution > 0 else "baisse",
        "text": text,
    }


def top_reasons(
    row: pd.Series, contributions: pd.Series, reference_stats: dict, top_n: int = 3
) -> list[dict]:
    """Sélectionne les top_n variables qui ont le plus pesé (en valeur absolue).

    Args:
        row: les variables d'une fiche (joueur, match).
        contributions: contribution SHAP de chaque variable pour cette fiche.
        reference_stats: médianes des joueurs honnêtes par rang (produites à l'entraînement).
        top_n: nombre de raisons à renvoyer.
    """
    ordered = contributions.abs().sort_values(ascending=False).index[:top_n]
    rank_refs = reference_stats.get(str(int(row["rank_tier"])), {})
    return [
        build_reason(feature, row[feature], contributions[feature], rank_refs.get(feature))
        for feature in ordered
    ]


def reference_by_rank(train_df: pd.DataFrame) -> dict:
    """Médiane de chaque variable numérique chez les joueurs HONNÊTES, rang par rang.

    Sert de point de comparaison dans les explications : on compare un joueur à des
    joueurs honnêtes de même niveau, pas à la moyenne générale (un joueur de rang 8 est
    naturellement meilleur qu'un joueur de rang 2).
    """
    honest = train_df[train_df["is_cheater"] == 0]
    medians = honest.groupby("rank_tier")[NUMERIC_FEATURES].median().round(3)
    return {str(rank): values.to_dict() for rank, values in medians.iterrows()}


def _original_feature(transformed_name: str) -> str:
    """Retrouve la variable d'origine d'une colonne transformée.

    Exemples : "num__accuracy" -> "accuracy" ; "cat__input_device_manette" -> "input_device".
    """
    name = transformed_name.split("__", 1)[1]
    for feature in CATEGORICAL_FEATURES:
        if name.startswith(feature + "_"):
            return feature
    return name


def transformed_mean(model: Pipeline, X_train: pd.DataFrame) -> list[float]:
    """Moyenne des données d'entraînement après preprocessing.

    C'est le "joueur moyen" de référence pour expliquer un modèle linéaire. On ne
    conserve que cette moyenne, jamais les données d'entraînement elles-mêmes
    (minimisation des données).
    """
    X_transformed = model.named_steps["preprocessing"].transform(X_train[FEATURES])
    if hasattr(X_transformed, "toarray"):
        X_transformed = X_transformed.toarray()
    return np.asarray(X_transformed).mean(axis=0).round(6).tolist()


def compute_contributions(
    model: Pipeline, X: pd.DataFrame, background_mean: list[float] | None = None
) -> pd.DataFrame:
    """Calcule la contribution de chaque variable d'origine au score, ligne par ligne.

    Le modèle est un Pipeline (preprocessing + classifieur). L'explication est calculée
    sur les données transformées, puis les colonnes issues d'une même variable
    catégorielle (encodage one-hot) sont additionnées pour revenir aux variables
    d'origine. C'est permis car ces contributions sont additives.

    - Modèle linéaire (régression logistique) : contribution exacte
      = coefficient x (valeur - valeur moyenne d'entraînement). C'est exactement ce que
      calcule SHAP pour un modèle linéaire, sans avoir besoin de la bibliothèque.
    - Modèle à arbres (gradient boosting) : SHAP TreeExplainer, algorithme exact dédié.

    Args:
        model: le Pipeline entraîné.
        X: les fiches à expliquer.
        background_mean: moyenne des données d'entraînement transformées (obligatoire
            pour un modèle linéaire, voir transformed_mean).

    Returns:
        Un DataFrame (une ligne par fiche, une colonne par variable d'origine), en
        log-odds : l'échelle interne du modèle avant la conversion en probabilité.
    """
    preprocessing = model.named_steps["preprocessing"]
    classifier = model.named_steps["model"]
    X_transformed = preprocessing.transform(X[FEATURES])
    if hasattr(X_transformed, "toarray"):  # matrice creuse -> matrice classique
        X_transformed = X_transformed.toarray()
    X_transformed = np.asarray(X_transformed, dtype=float)
    names = preprocessing.get_feature_names_out()

    if hasattr(classifier, "coef_"):
        if background_mean is None:
            raise ValueError("background_mean est requis pour expliquer un modèle linéaire.")
        values = classifier.coef_[0] * (X_transformed - np.asarray(background_mean))
    else:
        import shap  # import local : seul endroit du module qui dépend de SHAP

        explainer = shap.TreeExplainer(classifier)
        values = np.asarray(explainer.shap_values(X_transformed))
        if values.ndim == 3:  # certaines versions renvoient une sortie par classe
            values = values[..., 1]

    per_column = pd.DataFrame(values, columns=names, index=X.index)
    grouped = per_column.T.groupby(_original_feature).sum().T
    return grouped[FEATURES]


def explain(model: Pipeline, X: pd.DataFrame, explain_info: dict, top_n: int = 3) -> list:
    """Renvoie, pour chaque fiche de X, la liste de ses top_n raisons lisibles.

    Args:
        model: le Pipeline entraîné.
        X: les fiches à expliquer.
        explain_info: informations d'explication enregistrées avec le modèle
            ("reference_by_rank" et "background_mean", voir src/train.py).
        top_n: nombre de raisons par fiche.
    """
    contributions = compute_contributions(model, X, explain_info.get("background_mean"))
    return [
        top_reasons(X.loc[i], contributions.loc[i], explain_info["reference_by_rank"], top_n)
        for i in X.index
    ]
