# Journal de bord — Bloc 4 « Sentinel »

> Historique des étapes du projet, des décisions prises et de leur validation.
> Sert de fil conducteur pour la présentation et les questions du jury.
> Dernière mise à jour : 16 octobre 2026.

## Vue d'ensemble

| Étape | Contenu | État | Validation |
|---|---|---|---|
| 0 | Installation de l'environnement | ✅ | Versions vérifiées sur le Mac |
| 1 | Choix du sujet, cahier des charges, structure du dépôt | ✅ | Cahier des charges validé |
| 2 | Données synthétiques et contrat de données | ✅ | 14 tests |
| 3 | Modèle (sélection, seuil, versionnement) | ✅ | Seuils d'acceptation atteints |
| 4 | Explicabilité SHAP, audit d'équité, notebooks | ✅ | Notebooks exécutés sur le Mac |
| 5 | Robustesse et montée en charge | ✅ | 22 tests |
| 6 | API FastAPI, Postgres, droits RGPD, Docker | ✅ | Parcours de 6 tests validé sur le Mac |
| 6b | Console de modération | ✅ | Parcours vérifié dans un navigateur ; test sur le Mac à confirmer |
| 7 | Documentation RGPD détaillée | ⏳ | — |
| 8 | CI/CD GitHub Actions | ⏳ | — |
| 9 | Monitoring de la dérive (Evidently) | ⏳ | — |
| 10 | Réentraînement automatisé | ⏳ | — |
| 11 | Documentation finale (architecture, fiche modèle, traçabilité) | ⏳ | — |
| 12 | Slides et vidéo | ⏳ | — |
| 13 | Audit final contre la grille et entraînement au jury | ⏳ | — |

Total actuel : **108 tests automatisés**, `ruff` sans erreur, 4 Pull Requests fusionnées.

---

## Étape 0 — Environnement

| Outil | Version |
|---|---|
| Mac | Apple Silicon (arm64) |
| Git | 2.39.5 |
| Docker / Docker Compose | 29.8.2 / v5.6.0 |
| Python | 3.11.9 (même version que l'image Docker) |
| VS Code | 1.141.1 + extensions Python, Jupyter, Container Tools, Claude Code |

**Pourquoi Python 3.11 en local et dans Docker :** reproductibilité, avec les mêmes versions partout (critère 3.5).

---

## Étape 1 — Sujet et cahier des charges

### Choix du sujet

1. Sujet initial : prédiction d'attrition client (e-commerce sport). **Abandonné** avant toute ligne de code, car jugé trop classique.
2. Sujets étudiés : anti-triche, abandon de joueurs F2P, rage quit, bots MMO, smurfing, piratage de comptes, toxicité du chat.
3. **Retenu : détection de triche** dans *Arena Strike*, un jeu de tir tactique 5v5 fictif (type Valorant / CS2) du studio fictif Nebula Forge.
4. API Riot évaluée puis **écartée** :
   - aucune étiquette de bannissement disponible ;
   - Valorant réservé aux clés de production avec consentement des joueurs ;
   - clé de développement qui expire toutes les 24 h ;
   - traitement de données personnelles de vrais joueurs sans base légale ;
   - dérive non contrôlable pour la démo.

   → **Données synthétiques**, choix justifié dans le README.

### Cahier des charges (`docs/cahier_des_charges.md`)

- **Objectif** : prioriser la file de revue des modérateurs. Environ 30 000 fiches par jour, pour une capacité de revue de 300 fiches (1 %).
- **Aide à la décision uniquement** : aucun bannissement automatique (article 22 du RGPD).
- **Pièges d'équité identifiés** :
  - joueurs honnêtes à la manette, plus précis grâce à l'assistance à la visée ;
  - joueurs utilisant l'option d'accessibilité.
- **Aucune donnée sensible** (article 9). Les variables d'audit (`age_band`, `accessibility_mode`) ne sont jamais utilisées par le modèle et ne sont analysées que de façon agrégée.
- **Accessibilité** : console conforme aux bases du RGAA, test d'équité sur le groupe accessibilité.

### Décisions techniques

| Décision | Choix | Justification |
|---|---|---|
| Orchestration | Docker Compose plutôt que Kubernetes | Un seul hôte, charge modérée, API sans état donc migrable vers Kubernetes sans modifier le code |
| Qualité du code | ruff dans la CI | Prouver le respect de PEP 8 au lieu de l'affirmer (critère 6.5) |
| Réentraînement | GitHub Actions planifié | Aucun outil supplémentaire |
| Base de données | Postgres | Cohérence avec le bloc 2, traçabilité |
| Modèle versionné dans Git | Oui | Un clonage suffit à reproduire la démo |
| Graphiques de la console | SVG fait main (au lieu de Chart.js) | Aucune ressource externe (RGPD, CSP stricte) |
| Fonctionnement Git | Branche + Pull Request par étape | Historique lisible ; les fusions apparaissent au nom de Noah |

---

## Étape 2 — Données synthétiques

**Fichiers :** `src/config.py`, `src/data/generate.py`, `src/data/validate.py`, `tests/test_data.py`

- Générateur reproductible (graine fixe) : environ 3 % de tricheurs (aimbot 70 %, wallhack 30 %).
- Réalisme ajouté après un premier modèle « parfait » (PR-AUC 0,997, signe de données trop simples) :
  - tricheurs discrets (triche sur 70 % de leurs matchs seulement, force variable) ;
  - 3 % de joueurs honnêtes surdoués ;
  - davantage de bruit de mesure.
- Paramètre `cheat_intensity` : 1,0 pour la triche flagrante, 0,4 pour la **triche humanisée** (scénario de dérive).
- Validation du contrat : colonnes, valeurs manquantes, bornes, catégories, cible, doublons. Toutes les erreurs sont réunies dans un seul message.
- Correction en cours de route : la règle `data/` du `.gitignore` excluait aussi `src/data/`, remplacée par `/data/`.

---

## Étape 3 — Modèle

**Fichiers :** `src/features.py`, `src/evaluate.py`, `src/train.py`, `models/cheat_model_v1.*`, `tests/test_model.py`

- **Découpage par joueur** en entraînement, validation et test (60/20/20), pour éviter toute fuite de données.
- Deux candidats : régression logistique (référence) et **gradient boosting (retenu)**. PR-AUC de validation : 0,590 contre 0,582.
- **Seuil de décision** : le plus bas qui garde au plus 1 % de faux positifs, fixé sur la validation. Valeur retenue : 0,692.
- **Seuils d'acceptation révisés** après une étude de faisabilité sur 5 graines (PR-AUC entre 0,52 et 0,62). Le seuil initial de 60 % de précision était irréaliste par construction.
- Bug corrigé dans le calcul du seuil, qui faussait la comparaison avec la règle des signalements.

### Résultats du modèle v1 (jeu de test)

| Métrique | Règle des signalements | Sentinel v1 | Seuil |
|---|---|---|---|
| PR-AUC | 0,11 | **0,59** | ≥ 0,45 ✅ |
| ROC-AUC | 0,68 | **0,87** | ≥ 0,80 ✅ |
| Précision sur le 1 % le plus suspect | 30 % | **94 %** | ≥ 80 % ✅ |
| Rappel | 10 % | **57 %** | ≥ 40 % ✅ |
| Taux de faux positifs | 0,6 % | 1,3 % | ≤ 1,5 % ✅ |

**Traçabilité :** `models/cheat_model_v1.json` contient les métriques, l'empreinte des données (`7918e99aef9199a7`), la graine 42, le commit du code (`f839bff`) et la version de scikit-learn.

---

## Étape 4 — Explicabilité, équité, notebooks

**Fichiers :** `src/explain.py`, `src/fairness.py`, `src/viz.py`, `notebooks/01-03`, `tests/test_explain_fairness.py`

- **SHAP** : 3 raisons par prédiction, en français, comparées aux joueurs honnêtes du même rang. Exemple réel obtenu sur le Mac :
  > Éliminations à travers la fumée : 23 % (joueurs honnêtes de son rang : 2 %), qui augmente le risque
- **Audit d'équité intégré aux critères d'acceptation** : un modèle inéquitable n'est jamais promu.

| Groupe audité | Écart max. de faux positifs | Limite |
|---|---|---|
| Périphérique (manette / clavier-souris) | 0,7 point | < 2 ✅ |
| Plateforme | 0,6 point | < 2 ✅ |
| Mode accessibilité | 0,3 point | < 2 ✅ |
| Tranche d'âge | 0,8 point | < 2 ✅ |

- Constat clé : les joueurs à la manette ne sont **pas** davantage soupçonnés (0,85 % de faux positifs, contre 1,5 % au clavier-souris), malgré une précision naturellement plus élevée.
- **Validation :** les 3 notebooks ont été exécutés sur le Mac, SHAP compris, et commités par Noah (`5a176fb`).

---

## Étape 5 — Robustesse et montée en charge

**Fichiers :** `tests/test_robustness.py`, `src/benchmark.py`, `tests/test_performance.py`

- Aucun plantage face aux valeurs manquantes (sur n'importe quelle variable), aux valeurs aberrantes ou aux catégories inconnues.
- Bruit de mesure de 5 % : 97 des 100 fiches les plus suspectes restent en tête. Perte de 30 % de la télémétrie : PR-AUC quasi inchangée.
- Latence p95 d'une fiche : environ 5 ms. 100 000 fiches traitées en environ 0,2 s.
- **Découverte importante** : avec `class_weight="balanced"`, le score n'est **pas une probabilité calibrée**. C'est un **score de suspicion** qui sert à classer. Le test de bruit juge donc la stabilité des décisions, et l'interface parle de « score », jamais de pourcentage de chances.

---

## Étape 6 — API, Postgres, RGPD, Docker

**Fichiers :** `api/*.py`, `Dockerfile`, `docker-compose.yml`, `requirements-api.txt`, `tests/test_api.py`, `tests/test_repository.py`

| Route | Rôle |
|---|---|
| `GET /health` | État du service |
| `GET /model-info` | Métriques, équité et traçabilité du modèle |
| `POST /predict` | Score + priorité + 3 raisons |
| `POST /predict/batch` | File de revue triée (1 000 fiches au maximum) |
| `POST /profiles/validate` | Validation ligne par ligne d'un import |
| `POST /players/{id}/decisions` | Décision humaine |
| `GET /players/{id}/data` | Droit d'accès (art. 15) |
| `DELETE /players/{id}/data` | Droit à l'effacement (art. 17), différé si triche confirmée |

**Sécurité :**
- clé d'API comparée en temps constant, et **démarrage refusé si la clé vaut `change-me`** ;
- validation stricte des entrées, avec refus des variables d'âge et d'accessibilité ;
- requêtes SQL paramétrées (un test vérifie l'absence d'injection) ;
- Postgres non exposé hors du réseau Docker ;
- conteneur non-root, en lecture seule, avec limites CPU et mémoire ;
- logs JSON sans aucune donnée de joueur.

**Choix de disponibilité :** si la base tombe, la prédiction est quand même renvoyée et l'incident est journalisé.

**Validation sur le Mac :**
- Docker Compose démarré : Postgres et l'API sont en état sain.
- Incident instructif : l'API a refusé de démarrer avec la clé par défaut. C'est la protection attendue, et elle a obligé à régénérer la base avec les bons identifiants.
- Parcours de 6 tests dans `/docs` validé : prédiction suspecte, prédiction honnête, erreur 422, variable d'âge refusée, décision enregistrée, droits d'accès et effacement différé (409).

---

## Étape 6b — Console de modération

**Fichiers :** `api/static/console/*`, `api/validation.py`

- **Onglets :**
  1. Importer : CSV validé ligne par ligne, motifs de rejet en français.
  2. File de revue : histogramme des scores avec le seuil, filtres.
  3. Santé du modèle : carte d'identité, comparaison avec la règle des signalements, audit d'équité.
- **Fiche joueur** : raisons SHAP, statistiques du match, décision humaine enregistrée dans Postgres.
- **Aucune ressource externe** : polices IBM Plex (licence OFL) et graphiques SVG servis par l'API. Une CSP stricte bloque tout appel à un tiers et tout script injecté.
- **Accessibilité** : lien d'évitement, navigation clavier, focus visible, priorité indiquée par une icône et un texte, tableau de données sous chaque graphique, animations désactivées si l'utilisateur le demande.
- **Validation :** parcours complet vérifié dans Chromium (import de 153 lignes, dont 150 valides et 3 rejetées, analyse, fiche, décision, filtres). **Test sur le Mac à confirmer.**

---

## Couverture de la grille (état au 16/10)

| Critère | État | Où |
|---|---|---|
| 1.1 Exigences et accessibilité | 🟢 | Cahier des charges, console RGAA, audit accessibilité. Manque : matrice de traçabilité (étape 11) |
| 1.2 Métriques adaptées | 🟢 | `src/evaluate.py`, notebook 02 |
| 1.3 Robustesse | 🟢 | `tests/test_robustness.py` |
| 1.4 Évolutivité | 🟢 | `src/benchmark.py`, API sans état |
| 1.5 Explicabilité | 🟢 | SHAP en français, notebook 03, console |
| 2.1 Compatibilité avec l'infrastructure | 🟢 | Contrat de données, Postgres, JSON |
| 2.2 Temps de réponse et ressources | 🟢 | p95 ≈ 5 ms, limites Compose |
| 2.3 Erreurs, logs, alertes | 🟡 | Erreurs et logs faits ; **alertes à l'étape 9** |
| 2.4 Maintenabilité | 🟢 | Modules, 108 tests, versions |
| 2.5 Sécurité | 🟢 | Clé, validation, SQL paramétré, CSP |
| 3.1 à 3.5 Réentraînement | 🔴 | Étapes 9 et 10 (reproductibilité déjà prête : graine, empreinte, commit) |
| 4.1 à 4.6 CI/CD | 🔴 | Étape 8 |
| 5.1 et 5.2 RGPD / Informatique et Libertés | 🟡 | Droits d'accès et d'effacement, purge, minimisation ; **registre à rédiger (étape 7)** |
| 5.3 Sécurité | 🟡 | Mesures techniques faites ; **2FA GitHub et FileVault à confirmer** |
| 5.4 ISO 27001 | 🟡 | Principes à documenter (étape 7, lien avec le bloc 1) |
| 5.5 IA éthique | 🟢 | SHAP, audit d'équité, revue humaine |
| 6.1 à 6.8 Qualité du code | 🟢 | Structure, docstrings, ruff, tests, commits clairs |
| 7.1 à 7.7 Présentation | 🔴 | Étapes 12 et 13 |

---

## Points ouverts

1. **Self-hosted runner** sur le Mac pour un déploiement entièrement automatique (critère 4.4). Décision à prendre à l'étape 8.
2. **2FA GitHub et FileVault** à activer ou confirmer (critère 5.3).
3. Notebook 03 : afficher 3 joueurs **différents** dans les explications individuelles.
4. Quand le démarrage de l'API échoue, le conteneur redémarre en boucle : prévoir un arrêt propre.
5. Questions « jury » des étapes 3 à 6 à travailler pendant la relecture du code.
6. Usage de l'IA : section du README à jour. Les commits de code portent la mention `Co-Authored-By: Claude`, et les fusions de Pull Requests apparaissent au nom de Noah.

## Prochaine étape

**Étape 8 : CI/CD avec GitHub Actions.** Tests, ruff et build Docker à chaque push, publication de l'image à chaque version, déploiement automatique.
