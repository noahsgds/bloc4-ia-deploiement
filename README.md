# Sentinel — Détection de triche par IA (bloc 4)

Solution d'IA qui priorise la file de revue des modérateurs d'**Arena Strike**,
un jeu de tir tactique 5v5 fictif (studio fictif Nebula Forge), en estimant la
probabilité de triche de chaque joueur sur chaque match.

> Projet réalisé pour la certification « Architecte en Intelligence Artificielle » (RNCP, niveau 7).
> Toutes les données sont synthétiques.

## Cahier des charges

Voir [docs/cahier_des_charges.md](docs/cahier_des_charges.md).

## Structure du dépôt

| Dossier | Contenu |
|---|---|
| `notebooks/` | Exploration, modélisation, explicabilité et audit de biais |
| `src/` | Génération des données, preprocessing, entraînement, évaluation |
| `tests/` | Tests automatisés (pytest) |
| `models/` | Modèle champion versionné et ses métadonnées |
| `api/` | API de prédiction (FastAPI) |
| `monitoring/` | Détection de drift (Evidently) |
| `retrain/` | Réentraînement automatisé |
| `.github/workflows/` | Pipelines CI/CD (GitHub Actions) |
| `docs/` | Cahier des charges, architecture, RGPD, fiche modèle |

## Installation

Prérequis : Python 3.11, Docker et Docker Compose.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Utilisation

| Commande | Effet |
|---|---|
| `python -m src.data.generate --output data/train.csv` | Génère 50 000 fiches synthétiques (graine 42) |
| `python -m src.data.generate --cheat-intensity 0.4 --seed 7 --output data/drift.csv` | Génère des données de « triche humanisée » (scénario de dérive) |
| `python -m src.train --version v2` | Entraîne, sélectionne, évalue et sauvegarde un modèle dans `models/` |
| `python -m src.benchmark` | Mesure la latence d'une prédiction et le débit par lot |
| `pytest -v` | Lance tous les tests |
| `ruff check .` | Vérifie le style et les erreurs courantes |

Les notebooks (`notebooks/`) s'ouvrent dans VS Code ou Jupyter et s'exécutent avec « Run All » :

1. `01_exploration` : déséquilibre des classes, signaux de triche, pièges d'équité, limites de la règle des signalements ;
2. `02_modelisation` : découpage par joueur, comparaison des modèles, choix du seuil, résultats sur le test ;
3. `03_explicabilite_biais` : importance des variables (SHAP), explications individuelles, audit d'équité.

## Résultats du modèle v1 (jeu de test)

| Métrique | Règle actuelle (signalements) | Sentinel v1 | Seuil d'acceptation |
|---|---|---|---|
| PR-AUC | 0,11 | 0,59 | ≥ 0,45 |
| ROC-AUC | 0,68 | 0,87 | ≥ 0,80 |
| Précision sur le 1 % le plus suspect | 30 % | 94 % | ≥ 80 % |
| Rappel au seuil de décision | 10 % | 57 % | ≥ 40 % |
| Taux de faux positifs | 0,6 % | 1,3 % | ≤ 1 % (tolérance 1,5 %) |
| Écart max. de faux positifs entre groupes | — | 0,75 point | < 2 points |

Détail complet (métriques, audit d'équité, empreinte des données, commit du code) :
`models/cheat_model_v1.json`.

## Robustesse et montée en charge

**Robustesse** (`tests/test_robustness.py`) : le modèle ne plante jamais et renvoie toujours
une probabilité valide, même avec des valeurs manquantes sur n'importe quelle variable, des
valeurs aberrantes ou des catégories inconnues (nouvelle plateforme). Il se dégrade
doucement : un bruit de mesure de 5 % garde 97 des 100 fiches les plus suspectes dans la
file de revue, et une perte de 30 % des temps de réaction ne fait presque pas baisser la
PR-AUC. Sans aucun signalement (panne du système), il reste nettement meilleur que le hasard.

**Montée en charge** (`python -m src.benchmark`, mesuré en local) :

| Mesure | Résultat | Exigence |
|---|---|---|
| Latence d'une fiche (p95) | ~5 ms | < 200 ms |
| Lot de 100 000 fiches | ~0,2 s (≈ 500 000 fiches/s) | volume quotidien ≈ 30 000 fiches |

Le temps croît proportionnellement au volume. Le modèle n'est donc pas le goulot
d'étranglement : la montée en charge se joue au niveau de l'API (plusieurs instances sans
état derrière un répartiteur de charge).

## Qualité du code

- Tests automatisés : `pytest`
- Style et erreurs courantes : `ruff check .` (configuration dans `pyproject.toml`)

## Choix techniques

### Docker Compose plutôt que Kubernetes (`/k8s`)

L'énoncé cite Kubernetes comme exemple d'orchestration. J'ai choisi Docker Compose
car la solution tourne sur un seul hôte, avec peu de services et une charge modérée.
Kubernetes apporterait l'auto-scaling et l'auto-réparation, au prix d'une complexité
d'exploitation non justifiée à ce stade. L'API étant sans état et conteneurisée, une
migration vers Kubernetes ne demanderait pas de modifier le code, seulement la couche
de déploiement.

### Données synthétiques plutôt que données réelles

Aucune source publique ne fournit d'étiquettes de triche (bannissements confirmés).
L'utilisation d'API de jeux existants a été évaluée puis écartée : absence d'étiquettes,
accès restreint, traitement de données personnelles de vrais joueurs sans base légale,
et dérive non contrôlable pour les démonstrations. Le générateur synthétique permet de
contrôler la vérité terrain, la reproductibilité (graine fixe) et la dérive.

## Usage de l'IA générative

Un assistant IA (Claude) a été utilisé pour l'accompagnement, la relecture et la
préparation de certains fichiers. Les commits concernés portent la mention
`Co-Authored-By: Claude`. Chaque choix technique et chaque ligne de code ont été
relus, compris et validés par l'auteur.
