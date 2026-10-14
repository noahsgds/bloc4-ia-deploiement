"""Configuration centrale du projet Sentinel.

Tous les paramètres partagés (graine, noms de colonnes, valeurs autorisées) sont
définis ici, et nulle part ailleurs : si une colonne change de nom, on ne la
modifie qu'à un seul endroit (principe DRY, "Don't Repeat Yourself").
"""

from pathlib import Path

# --- Chemins -----------------------------------------------------------------
# Racine du dépôt : le dossier parent de src/
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"  # ignoré par Git (données régénérables)

# --- Reproductibilité --------------------------------------------------------
# Graine aléatoire fixe : avec la même graine, le générateur produit exactement
# les mêmes données (critère 3.5 de la grille : reproductibilité).
RANDOM_SEED = 42

# --- Contrat de données (cahier des charges, section 4) ----------------------
# Identifiants : servent à relier les lignes, jamais utilisés pour prédire.
ID_COLUMNS = ["player_id", "match_id", "match_date"]

# Variables numériques utilisées par le modèle.
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

# Variables catégorielles utilisées par le modèle.
CATEGORICAL_FEATURES = ["input_device", "platform"]

# Variables d'audit : JAMAIS utilisées par le modèle, uniquement pour vérifier
# l'équité de façon agrégée (cahier des charges, section 8).
AUDIT_COLUMNS = ["age_band", "accessibility_mode"]

# Variable à prédire : 1 = tricheur confirmé, 0 = joueur honnête.
TARGET = "is_cheater"

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
ALL_COLUMNS = ID_COLUMNS + FEATURES + AUDIT_COLUMNS + [TARGET]

# Valeurs autorisées pour les variables catégorielles.
ALLOWED_CATEGORIES = {
    "input_device": {"clavier_souris", "manette"},
    "platform": {"pc", "console"},
    "age_band": {"16-17", "18-24", "25-34", "35+"},
}

# Bornes réalistes des variables numériques (utilisées par la validation).
# Une valeur hors de ces bornes signale une donnée corrompue.
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

# Colonnes qui peuvent contenir des valeurs manquantes (perte de télémétrie).
# Les autres doivent toujours être renseignées.
NULLABLE_COLUMNS = {"avg_reaction_ms"}
