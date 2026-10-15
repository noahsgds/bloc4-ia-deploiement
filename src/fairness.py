"""Audit d'équité du modèle (cahier des charges, sections 4, 5 et 8 ; critères 1.1 et 5.5).

Question posée : le modèle soupçonne-t-il à tort certains groupes de joueurs plus que
d'autres ? On compare, groupe par groupe, le taux de faux positifs (joueurs honnêtes
signalés à tort) et le rappel (tricheurs détectés).

Groupes audités :
- input_device : l'assistance à la visée de la manette rend les joueurs honnêtes plus précis ;
- platform : PC ou console ;
- accessibility_mode : option d'accessibilité du jeu (risque de pénaliser les joueurs concernés) ;
- age_band : tranche d'âge (protection des mineurs).

Les résultats sont uniquement AGRÉGÉS (taux par groupe, jamais par joueur), conformément
aux mesures de protection des variables d'audit (cahier des charges, section 8).
"""

import numpy as np
import pandas as pd

from src.config import MAX_FPR_GAP, TARGET

AUDITED_GROUPS = ["input_device", "platform", "accessibility_mode", "age_band"]

# En dessous de ce nombre de joueurs honnêtes, le taux de faux positifs d'un groupe est
# trop incertain pour conclure : le groupe est signalé "effectif insuffisant".
MIN_HONEST_FOR_FPR = 100


def group_rates(df: pd.DataFrame, flagged: np.ndarray, group: str) -> dict:
    """Taux de faux positifs et rappel pour chaque valeur d'un groupe.

    Args:
        df: données contenant la colonne du groupe et la cible.
        flagged: tableau booléen, True si le modèle a signalé la ligne comme suspecte.
        group: nom de la colonne à auditer.
    """
    rates = {}
    for value, rows in df.groupby(group).groups.items():
        position = df.index.get_indexer(rows)
        y = df[TARGET].to_numpy()[position]
        f = flagged[position]
        n_honest, n_cheaters = int((y == 0).sum()), int((y == 1).sum())
        rates[str(value)] = {
            "n_honest": n_honest,
            "n_cheaters": n_cheaters,
            "false_positive_rate": round(float(f[y == 0].mean()), 4) if n_honest else None,
            "recall": round(float(f[y == 1].mean()), 4) if n_cheaters else None,
            "reliable": n_honest >= MIN_HONEST_FOR_FPR,
        }
    return rates


def fairness_report(df: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict:
    """Rapport d'équité complet sur un jeu de données (en pratique : le jeu de test).

    Returns:
        Pour chaque groupe audité : les taux par valeur, l'écart maximal de taux de faux
        positifs entre valeurs (en points de pourcentage) et le verdict par rapport au
        seuil MAX_FPR_GAP du cahier des charges.
    """
    df = df.reset_index(drop=True)
    flagged = np.asarray(scores) >= threshold
    report = {}
    for group in AUDITED_GROUPS:
        rates = group_rates(df, flagged, group)
        # On ne compare que les valeurs dont l'effectif est suffisant.
        fprs = [r["false_positive_rate"] for r in rates.values() if r["reliable"]]
        gap = round(max(fprs) - min(fprs), 4) if len(fprs) >= 2 else 0.0
        report[group] = {
            "rates": rates,
            "fpr_gap": gap,
            "passed": gap < MAX_FPR_GAP,
        }
    return report


def fairness_passed(report: dict) -> bool:
    """True si aucun groupe audité ne dépasse l'écart maximal autorisé."""
    return all(group["passed"] for group in report.values())
