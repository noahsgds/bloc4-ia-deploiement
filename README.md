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
| `monitoring.yml` | Chaque jour à 6 h 17 UTC et à la demande | Contrôle de dérive et de performance → rapport HTML en artefact → ticket GitHub en cas d'alerte → lancement de `retrain.yml` |
| `retrain.yml` | Alerte de surveillance, ou à la demande | Entraînement d'un challenger → comparaison au champion → si promu : tous les tests avec le nouveau modèle, puis Pull Request à valider → résultat ajouté au ticket |
| `dependabot.yml` | Chaque semaine | Pull Requests automatiques de mise à jour des dépendances (pip, Actions, Docker) |

Publier une nouvelle version :

```bash
# 1. ajouter la section de la version dans CHANGELOG.md, puis :
git tag v1.1.0
git push origin v1.1.0
```

**Choix de déploiement retenu : publication sans déploiement automatique.** Il n'y a pas
de serveur de production dans ce projet (pas de cloud payant). La CD s'arrête donc à la
publication de l'image testée et de la Release ; on déploie avec
`SENTINEL_VERSION=1.0.0 docker compose -p sentinel-prod -f docker-compose.yml -f docker-compose.prod.yml up -d`.
Le job de déploiement automatique (test de fonctionnement et retour arrière) est prêt : il
suffit d'enregistrer une machine comme runner auto-hébergé et de créer la variable
`DEPLOY_ENABLED=true`. Un runner auto-hébergé n'est acceptable que sur un dépôt privé.

Sécurité du pipeline : permissions minimales déclarées job par job ; secrets (`API_KEY`,
`POSTGRES_PASSWORD`) stockés dans les secrets GitHub et jamais écrits dans le code ; jeton
GitHub temporaire pour le registre ; le fichier de configuration du déploiement est créé
avec des droits restreints puis supprimé ; l'image déployée est exactement celle testée par
la CI.

## Surveillance du modèle (dérive)

Un modèle juste au lancement ne le reste pas : le jeu évolue, les tricheurs s'adaptent.
`monitoring/drift_report.py` répond à deux questions distinctes.

| Contrôle | Question | Comment | Alerte si |
|---|---|---|---|
| Dérive des données | Les statistiques des matchs ont-elles changé ? | Evidently : distance de Wasserstein normalisée (nombres), Jensen-Shannon (catégories), par rapport au jeu d'entraînement | ≥ 25 % des variables ont une distance ≥ 0,1 |
| Dérive des prédictions | Le modèle signale-t-il plus ou moins de fiches ? | Même mesure sur le score, part de fiches au-dessus du seuil | Information, pas d'alerte seule |
| Performance | Le modèle se trompe-t-il davantage ? | PR-AUC et faux positifs sur les fiches dont la vérité est connue | PR-AUC −0,10 par rapport au test, ou > 2 % d'honnêtes signalés |

```bash
python -m monitoring.drift_report --scenario normal      # aucune alerte
python -m monitoring.drift_report --scenario patch       # mise à jour du jeu
python -m monitoring.drift_report --scenario humanisee   # triche plus discrète
python -m monitoring.drift_report --current matchs_recents.csv
```

Le rapport HTML Evidently et un résumé JSON sont écrits dans `monitoring/reports/`
(ignoré par Git). Le workflow `monitoring.yml` lance le contrôle chaque jour et à la
demande (onglet Actions → « Surveillance du modèle » → Run workflow, choix du scénario) ;
en cas d'alerte, il ouvre un ticket GitHub avec les raisons et lance le réentraînement.

Résultats des trois scénarios (30 000 nouvelles lignes, modèle v1) :

| Scénario | Variables qui dérivent | PR-AUC | Faux positifs | Statut |
|---|---|---|---|---|
| Normal | aucune | 0,56 | 1,0 % | ok |
| Patch du jeu (tout le monde vise mieux) | 4 / 13 (précision, headshots, réaction, kills/min) | 0,54 | **4,8 %** | alerte |
| Triche humanisée | **aucune** | **0,15** | 1,0 % | alerte |

Ce qu'il faut retenir :

- **La dérive des données ne suffit pas.** La triche humanisée ne change presque pas les
  statistiques globales (3 % de tricheurs), mais le modèle ne la voit plus. Seule la
  surveillance de performance la détecte.
- **Le patch du jeu ne fait pas rater les tricheurs, il accuse des innocents** : 4,8 %
  des joueurs honnêtes dépassent le seuil. C'est le risque le plus grave pour l'équité.
- **Pourquoi pas le test de Kolmogorov-Smirnov** (choix par défaut d'Evidently sous
  1 000 lignes, et test classique) : les matchs d'un même joueur ne sont pas indépendants
  et, avec des dizaines de milliers de lignes, ce test signale une dérive pour des écarts
  sans importance. On a constaté de fausses alertes sur des données normales. Une distance
  mesure l'ampleur de l'écart, pas seulement son existence.

Limite connue : en production, la vérité n'est connue que pour les fiches examinées par
les modérateurs (le 1 % le plus suspect), ce qui ne dit rien des tricheurs restés sous le
seuil. La parade prévue : faire examiner chaque jour un **petit échantillon tiré au
hasard** (par exemple 30 fiches) pour mesurer le rappel sans biais. Dans la démo, les
étiquettes synthétiques jouent ce rôle.

## Réentraînement automatique

`retrain/retrain.py` applique le principe **champion / challenger** : le modèle en
production (champion) n'est remplacé que par un nouveau modèle (challenger) qui prouve
qu'il fait mieux, sur des fiches qu'aucun des deux n'a vues.

```bash
python -m retrain.retrain --scenario patch            # fiches récentes de démonstration
python -m retrain.retrain --current fiches.csv        # export de fiches étiquetées
python -m retrain.retrain --scenario patch --dry-run  # décider sans rien enregistrer
python -m retrain.retrain --rollback v1               # retour à une version précédente
```

**Données.** Les fiches récentes (vérité connue après enquête) sont séparées par joueur :
50 % pour entraîner, 20 % pour recaler le seuil, 30 % pour l'examen final. Le challenger
apprend sur une **fenêtre glissante** des 50 000 fiches les plus récentes (anciennes +
nouvelles) : le modèle suit l'évolution du jeu et l'entraînement dure toujours ~3 s.
Les fiches récentes font foi : un joueur présent dans les nouvelles données est retiré
des anciennes (pas de doublon, aucun joueur examiné n'a été vu à l'entraînement). Un
format modifié ou des fiches sans étiquette arrêtent le réentraînement avec un message.

**Règles de promotion** (`promotion_decision`, toutes obligatoires) :

| Règle | Pourquoi |
|---|---|
| Gain de PR-AUC confirmé dans ≥ 95 % de 200 tirages aléatoires de joueurs, **ou** correction d'un champion qui dépasse 1,5 % de faux positifs | Sur 9 000 fiches, la PR-AUC varie de ±0,03 selon l'échantillon : un petit gain peut être un coup de chance |
| Pas de perte de PR-AUC récente (0,01, ou 0,05 si l'on corrige des faux positifs) | Protéger les innocents passe avant un léger recul |
| Pas d'« oubli » : PR-AUC sur l'ancien test − 0,05 au plus | Les anciennes triches existent toujours |
| Faux positifs ≤ 1,5 % (récents et anciens) | Tolérance du cahier des charges |
| Écart de faux positifs entre groupes < 2 points | Équité (appareil, plateforme, accessibilité, âge) |

Résultats à partir du modèle v1 (fiches jamais vues) :

| Scénario | Champion v1 | Challenger | Décision |
|---|---|---|---|
| Patch du jeu | PR-AUC 0,55 ; **5,2 %** de faux positifs | PR-AUC 0,59 ; **1,1 %** | Promu : corrige les faux positifs |
| Triche humanisée | PR-AUC 0,15 | PR-AUC 0,21 | Promu, **mais sous les seuils du cahier des charges** |

Le second cas est le plus instructif : réentraîner ne suffit pas quand la triche ne laisse
plus de trace dans les variables actuelles. Le rapport le signale ; la vraie réponse est
de nouvelles variables (par exemple la trajectoire de visée), donc un nouveau projet.

**Traçabilité (reproductibilité).** Chaque modèle enregistre dans sa fiche JSON : graine,
commit Git, version de scikit-learn, empreinte des données, version parente, rapport de
promotion complet et **recette** de ses données (`src/lineage.py`). La recette s'emboîte
(celle de v3 contient celle de v2, qui contient celle de v1) : on reconstruit à
l'identique les données de n'importe quel modèle, et l'empreinte le prouve. Les données
elles-mêmes ne sont pas dans Git (volume, et données personnelles en production).

**Mise en production : toujours validée par un humain.** Le workflow propose le nouveau
modèle dans une Pull Request ; la fusion puis la publication d'une version (tag) le
déploient via la CD. Pour que GitHub Actions puisse ouvrir cette Pull Request, cocher
*Settings → Actions → General → Allow GitHub Actions to create and approve pull requests* ;
sinon la branche est poussée et le lien pour ouvrir la PR est indiqué dans l'exécution.

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
