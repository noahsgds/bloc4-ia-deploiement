# Sentinel — Détection de triche par IA (bloc 4)

Solution d'IA qui aide les modérateurs d'**Arena Strike**, un jeu de tir tactique 5v5
fictif (studio fictif Nebula Forge) : chaque fiche (joueur, match) reçoit un **score de
suspicion** et 3 raisons en français, pour examiner d'abord les cas les plus suspects.
**Le modèle ne sanctionne jamais** : un modérateur décide toujours.

> Projet réalisé pour la certification « Architecte en Intelligence Artificielle » (RNCP, niveau 7).
> Toutes les données sont synthétiques.

| Document | Contenu |
|---|---|
| [Cahier des charges](docs/cahier_des_charges.md) | Besoin, données, métriques, exigences, critères d'acceptation |
| [Guide d'explication](docs/guide_explication.md) | Chaque partie du projet expliquée simplement, et ce qu'il faut dire au jury |
| [Architecture](docs/architecture.md) | Schéma, composants, flux, lien avec les autres blocs |
| [Fiche du modèle](docs/fiche_modele.md) | Données, résultats, équité, limites, usages exclus |
| [Matrice de traçabilité](docs/matrice_tracabilite.md) | Chaque exigence reliée au code et au test qui la vérifie |
| [RGPD](docs/rgpd.md) et [sécurité](docs/securite.md) | Registre, droits, analyse d'impact ; politique et analyse des risques |
| [Journal de bord](docs/journal_de_bord.md) | Étapes, décisions et validations |

## Comment ça marche

```
Fiches de fin de match ──► API (FastAPI) ──► modèle ──► score + 3 raisons ──► console
                              │                                           │
                              ▼                                           ▼
                        Postgres : journal des prédictions   décision du modérateur
                              │
            surveillance quotidienne (dérive) ──► alerte ──► réentraînement
```

## Structure du dépôt

| Dossier | Contenu |
|---|---|
| `src/` | `data.py` (données synthétiques + contrôle du format), `model.py` (entraînement, mesures, équité), `explain.py` (raisons en français, SHAP) |
| `api/` | `main.py` (routes et sécurité), `schemas.py` (format des requêtes), `repository.py` (Postgres), `purge.py` (RGPD), `static/console/` (page web) |
| `monitoring/` | `monitor.py` : surveillance de la dérive (Evidently) |
| `retrain/` | `retrain.py` : réentraînement et retour arrière |
| `models/` | Modèle en production, sa fiche JSON et son échantillon de référence |
| `notebooks/` | Exploration, modélisation, explicabilité et équité |
| `tests/` | 50 tests automatisés (pytest) |
| `.github/workflows/` | CI, CD et surveillance quotidienne (GitHub Actions) |

## Installation et commandes

Prérequis : Python 3.11, Docker et Docker Compose.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

| Commande | Effet |
|---|---|
| `python -m src.model` | Génère 50 000 fiches, entraîne, évalue et enregistre le modèle v1 |
| `python -m monitoring.monitor --scenario patch` | Contrôle de dérive (scénarios : `normal`, `patch`, `humanisee`) |
| `python -m retrain.retrain --scenario patch` | Réentraîne et remplace le modèle s'il est meilleur et équitable |
| `python -m retrain.retrain --rollback v1` | Revient à la version v1 |
| `pytest -v` | Lance tous les tests |
| `ruff check .` | Vérifie le style et les erreurs courantes |

Les notebooks s'ouvrent dans VS Code et s'exécutent avec « Run All ».

## Lancer le service avec Docker

```bash
cp .env.example .env          # puis remplacer les valeurs "change-me"
docker compose up --build     # Postgres, API et purge quotidienne
```

- Console de modération : <http://localhost:8000/> (clé `API_KEY`)
- Documentation de l'API : <http://localhost:8000/docs> (bouton « Authorize »)

| Route | Rôle |
|---|---|
| `GET /health` | Le service fonctionne-t-il ? (sans clé) |
| `GET /model-info` | Version, mesures et équité du modèle en production |
| `POST /predict` | Score et 3 raisons pour 1 à 1 000 fiches, triées de la plus à la moins suspecte |
| `POST /players/{id}/decisions` | Décision humaine d'un modérateur |
| `GET /players/{id}/data` | Droit d'accès RGPD |
| `DELETE /players/{id}/data` | Droit à l'effacement RGPD (différé si une sanction est contestée) |

**Console** (2 onglets) : *File de revue* (import d'un CSV, lignes invalides expliquées,
fiches triées par score) et *Fiche* (3 raisons, statistiques du match, décision du
modérateur). Accessibilité : navigation au clavier, libellés, contrastes, priorité indiquée
par un symbole et un texte, pas seulement par la couleur.

**Sécurité** : clé d'API obligatoire, entrées validées (erreur 422 en français), champs non
prévus refusés, SQL paramétré, base non exposée, conteneurs sans droits root, aucune
ressource externe dans la console (CSP).

## Résultats du modèle v1 (jeu de test, 10 000 fiches jamais vues)

| Mesure | Règle actuelle (trier par signalements) | Sentinel v1 | Objectif |
|---|---|---|---|
| PR-AUC | 0,11 | **0,59** | ≥ 0,45 |
| ROC-AUC | 0,68 | **0,87** | ≥ 0,80 |
| Vrais tricheurs dans le 1 % examiné | 30 % | **94 %** | ≥ 80 % |
| Tricheurs détectés au seuil | 10 % | **57 %** | ≥ 40 % |
| Honnêtes signalés à tort | 0,6 % | 1,3 % | ≤ 1 % (tolérance 1,5 %) |
| Écart d'équité maximal entre groupes | — | 0,75 point | < 2 points |

Deux modèles ont été comparés : régression logistique (PR-AUC 0,58 en validation) et
gradient boosting (0,59), retenu. Détail : `models/cheat_model_v1.json`.

## CI/CD (GitHub Actions)

| Workflow | Quand | Ce qu'il fait |
|---|---|---|
| `ci.yml` | Chaque modification | Style (ruff), tests (avec une vraie base Postgres), construction de l'image Docker et test de démarrage |
| `cd.yml` | Publication d'une version (`git tag v1.1.0`) | CI complète, image publiée sur `ghcr.io`, Release GitHub avec les notes du CHANGELOG |
| `monitoring.yml` | Chaque jour, ou à la demande | Contrôle de dérive, rapport HTML ; en cas d'alerte : réentraînement automatique, Pull Request du nouveau modèle s'il passe les 3 règles, ticket GitHub |
| `dependabot.yml` | Chaque semaine | Propose les correctifs de sécurité des dépendances |

Mise en production d'une version publiée (pas de serveur de production dans ce projet,
donc pas de déploiement automatique) :
`SENTINEL_VERSION=1.0.0 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
L'image déployée est exactement celle que la CI a testée.

## Surveillance et réentraînement

**Surveillance** (`monitoring/monitor.py`) : deux contrôles.
1. *Les données ont-elles changé ?* Evidently compare les fiches récentes à l'échantillon
   de référence gardé avec le modèle. Alerte si au moins 25 % des variables dérivent.
2. *Le modèle se trompe-t-il davantage ?* Sur les fiches dont la vérité est connue :
   alerte si la PR-AUC perd plus de 0,10 ou si plus de 2 % d'honnêtes sont signalés.

**Réentraînement** (`retrain/retrain.py`) : un nouveau modèle apprend sur 70 % des fiches
récentes ; l'ancien et le nouveau passent le même examen sur les 30 % restants. Le nouveau
remplace l'ancien seulement s'il est **meilleur**, signale **au plus 1,5 % d'honnêtes** et
reste **équitable**. Chaque version garde sa graine, l'empreinte de ses données, le commit
du code et sa version parente ; retour arrière en une commande.

**Automatisation** (`.github/workflows/monitoring.yml`) : chaque jour, la surveillance tourne
sur GitHub Actions. En cas d'alerte, le réentraînement se lance **automatiquement** ; si le
nouveau modèle respecte les 3 règles, il est poussé sur une branche et proposé en Pull
Request, et un ticket résume la surveillance et le réentraînement. La mise en production
reste validée par un humain, qui relit et fusionne : le modèle ne se remplace jamais seul.

| Scénario (30 000 fiches) | Surveillance | Réentraînement |
|---|---|---|
| Normal | ok | Nouveau modèle pas meilleur : v1 conservé |
| Patch du jeu (tout le monde vise mieux) | Alerte : 4 variables dérivent, 4,9 % d'honnêtes signalés | Nouveau modèle : 0,85 % d'honnêtes signalés, promu |
| Triche humanisée | Alerte : PR-AUC 0,59 → 0,15, **sans dérive des données** | Promu (0,22) mais insuffisant : il faut de nouvelles variables |

Ce qu'il faut retenir : une triche qui change de forme ne se voit pas dans les données, seulement
dans la performance ; et le réentraînement corrige un jeu qui a changé, pas une triche invisible.

Limite : en production, la vérité n'est connue que pour les fiches examinées. Il faudrait
faire examiner chaque jour un petit échantillon tiré au hasard pour mesurer sans biais.

## Choix techniques

- **Un seul dépôt plutôt que deux** (l'énoncé cite un dépôt « modèle » et un dépôt
  « déploiement ») : les dossiers attendus sont tous présents (`/notebooks`, `/src`, `/tests`,
  `/models`, `requirements.txt` ; `/api`, `/monitoring`, `/retrain`, `Dockerfile`,
  `.github/workflows/`). Un seul dépôt garantit que l'API sert exactement le modèle testé
  dans le même commit, et évite de synchroniser deux historiques pour une équipe d'une personne.
- **Docker Compose plutôt que Kubernetes** (`/k8s` de l'énoncé) : un seul serveur, trois
  services, charge modérée. Kubernetes apporterait la mise à l'échelle automatique au prix
  d'une complexité non justifiée. L'API étant sans état, une migration ne changerait pas le code.
- **Données synthétiques** : aucune source publique ne fournit de bannissements confirmés.
  L'API de Riot Games a été évaluée puis écartée (pas d'étiquettes de triche, données de
  vrais joueurs sans base légale, dérive impossible à contrôler pour la démonstration).
- **Score de suspicion, pas une probabilité** : le modèle donne plus de poids aux tricheurs
  (très rares) ; ses scores servent à trier, pas à estimer un pourcentage.

## Usage de l'IA générative

Un assistant IA (Claude) a été utilisé pour l'accompagnement, la relecture et la
préparation de fichiers, en particulier la console web. Les commits concernés portent la
mention `Co-Authored-By: Claude`. Chaque choix a été relu, compris et validé par l'auteur.
