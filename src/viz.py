"""Style commun des graphiques des notebooks (lisibles, accessibles, cohérents).

Règles appliquées :
- palette validée pour les daltoniens (bleu / orange, jamais rouge / vert seuls) ;
- l'identité d'une série n'est jamais portée par la couleur seule : légende ou
  étiquette directe systématique ;
- un seul axe vertical par graphique, grille discrète, traits fins.
"""

import matplotlib.pyplot as plt

# Couleurs catégorielles, toujours dans cet ordre.
BLUE = "#2a78d6"  # série 1 : joueurs honnêtes / modèle Sentinel
ORANGE = "#eb6834"  # série 2 : tricheurs / règle actuelle
GRAY = "#52514e"  # texte secondaire et repères

HONEST_CHEATER_COLORS = {0: BLUE, 1: ORANGE}
HONEST_CHEATER_LABELS = {0: "Honnêtes", 1: "Tricheurs"}


def apply_style() -> None:
    """Applique le style à tous les graphiques suivants."""
    plt.rcParams.update(
        {
            "figure.figsize": (8, 4),
            "figure.dpi": 110,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": GRAY,
            "axes.labelcolor": "#0b0b0b",
            "axes.titleweight": "bold",
            "axes.titlesize": 12,
            "axes.grid": True,
            "grid.color": "#e6e5e1",
            "grid.linewidth": 0.6,
            "lines.linewidth": 2,
            "font.size": 10,
            "legend.frameon": False,
        }
    )
