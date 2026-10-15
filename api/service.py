"""Service de prédiction : charge le modèle champion et produit scores et explications.

Ce module fait le lien entre l'API (requêtes JSON) et le code du modèle (src/).
Il ne contient aucune logique de modélisation : il réutilise src/explain.py et le
modèle versionné dans models/ (même preprocessing qu'à l'entraînement, grâce au Pipeline).
"""

import math

import pandas as pd

from src.config import FEATURES, MODELS_DIR
from src.explain import FEATURE_LABELS, explain
from src.train import load_champion


def _plain(value):
    """Convertit les types numpy en types Python simples (pour le JSON)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    number = float(value)
    return None if math.isnan(number) else number


class ModelService:
    """Le modèle en production et ses métadonnées."""

    def __init__(self, models_dir=MODELS_DIR) -> None:
        self.model, self.metadata = load_champion(models_dir)
        self.version: str = self.metadata["version"]
        self.threshold: float = self.metadata["threshold"]

    def priority(self, score: float) -> str:
        """Niveau de priorité pour la file de revue, relatif au seuil de décision."""
        if score >= self.threshold:
            return "haute"
        if score >= self.threshold / 2:
            return "moyenne"
        return "basse"

    def predict(self, records: list[dict], with_reasons: bool = True) -> list[dict]:
        """Score, décision, priorité et raisons pour une liste de fiches.

        Args:
            records: fiches validées (dictionnaires conformes à MatchStats).
            with_reasons: calculer les 3 raisons lisibles (SHAP) pour chaque fiche.
        """
        frame = pd.DataFrame(records)
        # None -> NaN : la valeur manquante est ensuite imputée par le Pipeline du modèle.
        features = frame[FEATURES].astype({"avg_reaction_ms": float})
        scores = self.model.predict_proba(features)[:, 1]

        reasons = [[] for _ in records]
        if with_reasons:
            raw = explain(self.model, features, self.metadata["explain_info"])
            reasons = [
                [
                    {
                        **reason,
                        "value": _plain(reason["value"]),
                        "reference": _plain(reason["reference"]),
                    }
                    for reason in row
                ]
                for row in raw
            ]

        return [
            {
                "player_id": record["player_id"],
                "match_id": record["match_id"],
                "suspicion_score": round(float(score), 4),
                "flagged": bool(score >= self.threshold),
                "priority": self.priority(float(score)),
                "reasons": row_reasons,
                "model_version": self.version,
            }
            for record, score, row_reasons in zip(records, scores, reasons)
        ]

    def info(self) -> dict:
        """Résumé public du modèle (sans les références internes d'explication)."""
        fairness_gaps = {
            group: report["fpr_gap"] for group, report in self.metadata["fairness"].items()
        }
        return {
            "version": self.version,
            "model_name": self.metadata["model_name"],
            "created_at": self.metadata["created_at"],
            "git_commit": self.metadata["git_commit"],
            "threshold": self.threshold,
            "test_metrics": self.metadata["test_metrics"],
            "baseline_test_metrics": self.metadata["baseline_test_metrics"],
            "fairness_fpr_gaps": fairness_gaps,
            "acceptance": self.metadata["acceptance"],
            "data": self.metadata["data"],
            # Libellés français des variables, pour l'affichage dans la console.
            "feature_labels": {name: label for name, (label, _, _) in FEATURE_LABELS.items()},
        }
