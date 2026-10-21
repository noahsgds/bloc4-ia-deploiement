"""Réglages du projet Sentinel, rassemblés à un seul endroit.

Si une colonne ou un seuil change, on ne le modifie qu'ici.
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models"
REPORTS_DIR = ROOT_DIR / "monitoring" / "reports"

# Graine aléatoire fixe : mêmes données et même modèle à chaque exécution (reproductibilité).
RANDOM_SEED = 42

# --- Contrat de données (cahier des charges, section 4) ---------------------------------
ID_COLUMNS = ["player_id", "match_id", "match_date"]  # jamais utilisées pour prédire

NUMERIC_FEATURES = [
    "accuracy",
    "headshot_rate",
    "kd_ratio",
    "kills_per_min",
    "damage_per_round",
    "avg_reaction_ms",
    "kills_through_smoke_ratio",
    "rank_tier",
    "account_age_days",
    "hours_played_total",
    "reports_received",
]
CATEGORICAL_FEATURES = ["input_device", "platform"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Variables d'audit : JAMAIS données au modèle, seulement pour vérifier l'équité.
AUDIT_COLUMNS = ["age_band", "accessibility_mode"]
TARGET = "is_cheater"  # 1 = tricheur confirmé après enquête
ALL_COLUMNS = ID_COLUMNS + FEATURES + AUDIT_COLUMNS + [TARGET]

ALLOWED_CATEGORIES = {
    "input_device": {"clavier_souris", "manette"},
    "platform": {"pc", "console"},
    "age_band": {"16-17", "18-24", "25-34", "35+"},
}

# Bornes réalistes : une valeur en dehors signale une donnée corrompue.
NUMERIC_RANGES = {
    "accuracy": (0.0, 1.0),
    "headshot_rate": (0.0, 1.0),
    "kd_ratio": (0.0, 50.0),
    "kills_per_min": (0.0, 10.0),
    "damage_per_round": (0.0, 1000.0),
    "avg_reaction_ms": (50.0, 2000.0),
    "kills_through_smoke_ratio": (0.0, 1.0),
    "rank_tier": (1, 8),
    "account_age_days": (0, 5000),
    "hours_played_total": (0.0, 20000.0),
    "reports_received": (0, 50),
}
NULLABLE_COLUMNS = {"avg_reaction_ms"}  # perte de télémétrie possible

# --- Objectifs du modèle (cahier des charges, section 5) --------------------------------
REVIEW_SHARE = 0.01  # les modérateurs examinent 300 fiches sur 30 000 : le 1 % le plus suspect
MAX_FALSE_POSITIVE_RATE = 0.01  # au plus 1 % des joueurs honnêtes signalés à tort
FPR_TOLERANCE = 0.015  # tolérance du cahier des charges (variabilité d'un échantillon)
MAX_FPR_GAP = 0.02  # équité : écart maximal de faux positifs entre deux groupes

ACCEPTANCE_THRESHOLDS = {  # minimums mesurés sur le jeu de test
    "roc_auc": 0.80,
    "pr_auc": 0.45,
    "precision_top": 0.80,
    "recall": 0.40,
}

# --- Surveillance en production (étape 9) -----------------------------------------------
DRIFT_COLUMN_THRESHOLD = 0.1  # distance à partir de laquelle une variable a "dérivé"
DRIFT_SHARE_ALERT = 0.25  # alerte si au moins un quart des variables dérivent
MAX_PR_AUC_DROP = 0.10  # alerte si la PR-AUC perd plus de 0,10
MONITORING_MAX_FPR = 0.02  # alerte si plus de 2 % des honnêtes sont signalés
