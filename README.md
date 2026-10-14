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

_À compléter au fil du projet._

Prérequis : Python 3.11, Docker et Docker Compose.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

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
