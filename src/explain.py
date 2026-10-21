"""Explications des scores en français, pour les modérateurs (critères 1.5 et 5.5).

Exemple de raison produite :
    « Temps de réaction moyen : 112 ms (honnêtes de son rang : 262 ms) — augmente le risque »

Méthode SHAP : pour une fiche, SHAP répartit l'écart entre son score et le score moyen
entre les variables, comme on partagerait équitablement un gain entre coéquipiers.
Contribution positive = pousse vers "tricheur" ; négative = pousse vers "honnête".
On affiche les 3 variables qui ont le plus pesé.
"""

import math

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from src.config import CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES

# Libellé en français et format d'affichage de chaque variable.
FEATURE_LABELS = {
    "accuracy": ("Précision des tirs", "pct"),
    "headshot_rate": ("Taux de tirs à la tête", "pct"),
    "kd_ratio": ("Ratio éliminations / morts", "dec"),
    "kills_per_min": ("Éliminations par minute", "dec"),
    "damage_per_round": ("Dégâts par manche", "int"),
    "avg_reaction_ms": ("Temps de réaction moyen", "ms"),
    "kills_through_smoke_ratio": ("Éliminations à travers la fumée", "pct"),
    "rank_tier": ("Rang", "int"),
    "account_age_days": ("Ancienneté du compte", "jours"),
    "hours_played_total": ("Heures de jeu", "h"),
    "reports_received": ("Signalements reçus", "int"),
    "input_device": ("Périphérique", "cat"),
    "platform": ("Plateforme", "cat"),
}
CATEGORY_LABELS = {"manette": "manette", "clavier_souris": "clavier-souris", "pc": "PC"}


def format_value(feature: str, value) -> str:
    """Met une valeur en forme pour un humain : 0.31 -> "31 %", 182 -> "182 ms"."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "non mesuré"
    kind = FEATURE_LABELS[feature][1]
    if kind == "cat":
        return CATEGORY_LABELS.get(str(value), str(value))
    if kind == "pct":
        return f"{float(value) * 100:.0f} %"
    if kind == "dec":
        return f"{float(value):.2f}"
    unit = "" if kind == "int" else f" {kind}"
    return f"{float(value):.0f}{unit}"


def reference_by_rank(train_df: pd.DataFrame) -> dict:
    """Médiane de chaque variable chez les joueurs HONNÊTES, rang par rang.

    On compare un joueur à des honnêtes de même niveau : un joueur de rang 8 est
    naturellement meilleur qu'un joueur de rang 2.
    """
    honest = train_df[train_df["is_cheater"] == 0]
    medians = honest.groupby("rank_tier")[NUMERIC_FEATURES].median().round(3)
    return {str(rank): values.to_dict() for rank, values in medians.iterrows()}


def transformed_mean(model: Pipeline, train_df: pd.DataFrame) -> list[float]:
    """ "Joueur moyen" de l'entraînement, après préparation des données.

    Sert de point de comparaison pour expliquer la régression logistique. On ne garde
    que cette moyenne, jamais les données elles-mêmes.
    """
    X = model.named_steps["preprocessing"].transform(train_df[FEATURES])
    return np.asarray(X).mean(axis=0).round(6).tolist()


def contributions(model: Pipeline, X: pd.DataFrame, background_mean: list[float]) -> pd.DataFrame:
    """Contribution de chaque variable au score, pour chaque fiche.

    - Gradient boosting : SHAP (TreeExplainer, calcul exact pour les arbres).
    - Régression logistique : contribution = coefficient × (valeur − valeur moyenne),
      ce que SHAP calculerait aussi, sans besoin de la bibliothèque.
    Les colonnes 0/1 d'une même catégorie (ex. input_device_manette) sont additionnées
    pour revenir à la variable d'origine.
    """
    preprocessing, classifier = model.named_steps["preprocessing"], model.named_steps["model"]
    X_ready = np.asarray(preprocessing.transform(X[FEATURES]), dtype=float)
    if hasattr(classifier, "coef_"):
        values = classifier.coef_[0] * (X_ready - np.asarray(background_mean))
    else:
        import shap  # seul endroit du projet qui utilise SHAP

        values = np.asarray(shap.TreeExplainer(classifier).shap_values(X_ready))
        if values.ndim == 3:  # certaines versions renvoient une sortie par classe
            values = values[..., 1]

    def original(name: str) -> str:  # "cat__input_device_manette" -> "input_device"
        name = name.split("__", 1)[1]
        return next((f for f in CATEGORICAL_FEATURES if name.startswith(f + "_")), name)

    per_column = pd.DataFrame(values, columns=preprocessing.get_feature_names_out(), index=X.index)
    return per_column.T.groupby(original).sum().T[FEATURES]


def explain(model: Pipeline, X: pd.DataFrame, explain_info: dict, top_n: int = 3) -> list:
    """Pour chaque fiche, les ``top_n`` raisons principales, en phrases."""
    contrib = contributions(model, X, explain_info["background_mean"])
    all_reasons = []
    for i in X.index:
        row, c = X.loc[i], contrib.loc[i]
        references = explain_info["reference_by_rank"].get(str(int(row["rank_tier"])), {})
        reasons = []
        for feature in c.abs().sort_values(ascending=False).index[:top_n]:
            text = f"{FEATURE_LABELS[feature][0]} : {format_value(feature, row[feature])}"
            if feature in references:
                ref = format_value(feature, references[feature])
                text += f" (joueurs honnêtes de son rang : {ref})"
            rising = c[feature] > 0
            text += " — augmente le risque" if rising else " — diminue le risque"
            reasons.append(
                {
                    "feature": feature,
                    "contribution": round(float(c[feature]), 4),
                    "direction": "hausse" if rising else "baisse",
                    "text": text,
                }
            )
        all_reasons.append(reasons)
    return all_reasons
