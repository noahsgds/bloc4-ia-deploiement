# Sentinel — Détection de triche par IA (bloc 4)

Solution d'IA qui priorise la file de revue des modérateurs d'**Arena Strike**,
un jeu de tir tactique 5v5 fictif (studio fictif Nebula Forge), en estimant la
probabilité de triche de chaque joueur sur chaque match.

> Projet réalisé pour la certification « Architecte en Intelligence Artificielle » (RNCP, niveau 7).
> Toutes les données sont synthétiques.

## Cahier des charges

Voir [docs/cahier_des_charges.md](docs/cahier_des_charges.md).
Historique des étapes, décisions et validations : [docs/journal_de_bord.md](docs/journal_de_bord.md).

## Structure du dépôt

| Dossier | Contenu |
|---|---|
| `notebooks/` | Exploration, modélisation, explicabilité et audit de biais |
| `src/` | Génération des données, preprocessing, entraînement, évaluation |
| `tests/` | Tests automatisés (pytest) |
| `models/` | Modèle champion versionné et ses métadonnées |
| `api/` | API de prédiction (FastAPI), stockage Postgres, purge RGPD |
| `monitoring/` | Détection de drift (Evidently) |
| `retrain/` | Réentraînement automatisé |
| `.github/workflows/` | Pipelines CI/CD (GitHub Actions) |
| `docs/` | Cahier des charges, journal de bord, architecture, RGPD, fiche modèle |

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

## Console de modération

Une fois les services démarrés, la console est accessible sur <http://localhost:8000/>
(connexion avec la clé `API_KEY`).

| Onglet | Rôle |
|---|---|
| 01 Importer | Dépôt d'un CSV de fiches de match ; chaque ligne est validée par l'API et les rejets sont expliqués en français. Un fichier d'exemple (150 profils + 3 lignes invalides) est fourni. |
| 02 File de revue | Fiches triées par score de suspicion, priorité (icône + texte), raison principale, répartition des scores avec le seuil de décision. |
| Fiche joueur | Les 3 raisons du score comparées aux joueurs honnêtes du même rang, toutes les statistiques du match, et le formulaire de **décision humaine** enregistrée en base. |
| 03 Santé du modèle | Carte d'identité du modèle (version, commit, empreinte des données), comparaison avec la règle des signalements, audit d'équité, critères d'acceptation. |

Choix de conception :

- **Aucune ressource externe** : polices (IBM Plex, licence OFL) et graphiques (SVG) sont
  servis par l'API elle-même ; pas de CDN ni de Google Fonts, donc aucune donnée de
  navigation transmise à un tiers. Une politique CSP stricte l'impose.
- **Sécurité** : contenu inséré uniquement en texte (protection contre le XSS), clé d'API
  conservée le temps de l'onglet seulement.
- **Accessibilité (RGAA)** : lien d'évitement, navigation au clavier, focus visible, libellés
  de formulaires, contrastes renforcés, priorité jamais signalée par la couleur seule,
  tableau de données sous chaque graphique, animations désactivées si l'utilisateur le demande.

## Lancer l'API avec Docker

```bash
cp .env.example .env          # puis remplacer les valeurs "change-me"
docker compose up --build     # démarre Postgres puis l'API
```

- Documentation interactive : <http://localhost:8000/docs> (bouton « Authorize » : saisir la clé `API_KEY`)
- État du service : <http://localhost:8000/health>

| Route | Rôle |
|---|---|
| `GET /health` | État du service (sans authentification) |
| `GET /model-info` | Version, métriques, équité et traçabilité du modèle en production |
| `POST /predict` | Score de suspicion d'une fiche (joueur, match) et ses 3 raisons |
| `POST /predict/batch` | File de revue : jusqu'à 1 000 fiches triées de la plus à la moins suspecte |
| `POST /players/{id}/decisions` | Décision humaine d'un modérateur |
| `GET /players/{id}/data` | Droit d'accès RGPD : toutes les données d'un joueur |
| `DELETE /players/{id}/data` | Droit à l'effacement RGPD (différé si une sanction est en cours de contestation) |

Exemple :

```bash
curl -X POST http://localhost:8000/predict \
  -H "X-API-Key: <votre clé>" -H "Content-Type: application/json" \
  -d '{"player_id": "8274bbcc-1f0e-4c1a-9a51-6f2d3c4b5a69", "match_id": "0b9c2f4e-7d1a-4e3b-8c6f-2a1d9e8f7b65",
       "accuracy": 0.31, "headshot_rate": 0.42, "kd_ratio": 2.4, "kills_per_min": 1.2,
       "damage_per_round": 165, "avg_reaction_ms": 182, "kills_through_smoke_ratio": 0.21,
       "rank_tier": 6, "account_age_days": 22, "hours_played_total": 29, "reports_received": 3,
       "input_device": "clavier_souris", "platform": "pc"}'
```

Sécurité : clé d'API comparée en temps constant, validation stricte des entrées (erreur 422
explicite), variables d'audit refusées, requêtes SQL paramétrées, base de données non exposée
hors du réseau Docker, conteneur sans droits root et en lecture seule, limites CPU et mémoire.
En production, l'API serait placée derrière un reverse proxy assurant le HTTPS.

Purge RGPD des prédictions de plus de 12 mois : `docker compose exec api python -m api.purge`.

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

## CI/CD (GitHub Actions)

| Workflow | Déclencheur | Étapes |
|---|---|---|
| `ci.yml` | Chaque push et chaque Pull Request | ruff → tests pytest (avec une vraie base Postgres) → construction de l'image Docker → démarrage et prédiction de test dans le conteneur |
| `cd.yml` | Publication d'un tag `vX.Y.Z` | CI complète → image multi-architecture publiée sur `ghcr.io` → Release GitHub avec les notes du CHANGELOG → déploiement sur la machine d'exploitation avec test de fonctionnement et retour automatique à la version précédente en cas d'échec |
| `dependabot.yml` | Chaque semaine | Pull Requests automatiques de mise à jour des dépendances (pip, Actions, Docker) |

Publier une nouvelle version :

```bash
# 1. ajouter la section de la version dans CHANGELOG.md, puis :
git tag v1.1.0
git push origin v1.1.0
```

Sécurité du pipeline : permissions minimales déclarées job par job ; secrets (`API_KEY`,
`POSTGRES_PASSWORD`) stockés dans les secrets GitHub et jamais écrits dans le code ; jeton
GitHub temporaire pour le registre ; le fichier de configuration du déploiement est créé
avec des droits restreints puis supprimé ; l'image déployée est exactement celle testée par
la CI.

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
