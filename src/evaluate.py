"""Métriques d'évaluation du modèle (cahier des charges, section 5).

Pourquoi pas l'"accuracy" (taux de bonnes réponses) ? Avec environ 3 % de tricheurs,
un modèle qui répond toujours "honnête" aurait 97 % d'accuracy tout en étant inutile.
On utilise donc des métriques adaptées aux classes déséquilibrées.
"""

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve


def precision_at_top(y_true: np.ndarray, scores: np.ndarray, share: float) -> float:
    """Part de vrais tricheurs parmi les cas les plus suspects.

    Correspond à l'usage réel : les modérateurs n'examinent que le haut de la file.

    Args:
        y_true: étiquettes réelles (1 = tricheur).
        scores: probabilités de triche prédites.
        share: part des cas examinés (0.01 = le 1 % le plus suspect).
    """
    k = max(1, int(round(share * len(scores))))
    top_k = np.argsort(-scores)[:k]  # indices des k scores les plus élevés
    return float(np.mean(y_true[top_k]))


def threshold_for_max_fpr(y_true: np.ndarray, scores: np.ndarray, max_fpr: float) -> float:
    """Choisit le seuil de décision le plus bas qui garde le taux de faux positifs sous max_fpr.

    Taux de faux positifs = part des joueurs HONNÊTES signalés à tort. C'est le préjudice
    principal (être soupçonné à tort), donc on le plafonne d'abord, puis on maximise le
    nombre de tricheurs détectés sous cette contrainte.
    """
    fpr, _, thresholds = roc_curve(y_true, scores)
    allowed = np.where(fpr <= max_fpr)[0]
    # roc_curve renvoie les seuils du plus haut au plus bas : le dernier seuil autorisé
    # est le plus bas, donc celui qui détecte le plus de tricheurs.
    threshold = thresholds[allowed[-1]]
    if np.isinf(threshold):
        # Cas limite : aucun seuil ne respecte la contrainte, on ne signale personne
        # (seuil juste au-dessus du score le plus élevé).
        threshold = float(np.max(scores)) + 1e-9
    return float(threshold)


def compute_metrics(
    y_true: np.ndarray, scores: np.ndarray, threshold: float, review_share: float
) -> dict:
    """Calcule toutes les métriques de performance du cahier des charges.

    Returns:
        Un dictionnaire de métriques, arrondies pour être lisibles et enregistrées.
    """
    y_true = np.asarray(y_true)
    scores = np.asarray(scores)
    flagged = scores >= threshold
    honest = y_true == 0
    cheaters = y_true == 1

    return {
        "roc_auc": round(float(roc_auc_score(y_true, scores)), 4),
        "pr_auc": round(float(average_precision_score(y_true, scores)), 4),
        "precision_top": round(precision_at_top(y_true, scores, review_share), 4),
        "recall": round(float(flagged[cheaters].mean()), 4),
        "false_positive_rate": round(float(flagged[honest].mean()), 4),
        "threshold": round(float(threshold), 4),
        "n_samples": int(len(y_true)),
        "cheater_rate": round(float(cheaters.mean()), 4),
    }
