# Historique des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ;
numérotation [SemVer](https://semver.org/lang/fr/) : MAJEUR.MINEUR.CORRECTIF.

- **MAJEUR** : changement incompatible du contrat de l'API ou des données.
- **MINEUR** : nouvelle fonctionnalité compatible, ou nouveau modèle.
- **CORRECTIF** : correction sans changement de comportement attendu.

## [Non publié]

### Ajouté

- Surveillance quotidienne du modèle : dérive des données (Evidently) et performance sur
  les fiches étiquetées, statut ok/alerte, rapport HTML, ticket GitHub en cas d'alerte.
- Scénarios de démonstration : normal, mise à jour du jeu (`patch`), triche humanisée.
- Réentraînement sur les fiches récentes avec 3 règles de promotion (meilleur, au plus
  1,5 % d'honnêtes signalés, équitable) et retour arrière
  (`python -m retrain.retrain --rollback <version>`).
- Échantillon de référence enregistré avec chaque modèle (sans identifiant ni variable d'audit).
- Documentation RGPD (registre, AIPD, procédure des droits) et sécurité (politique,
  analyse des risques, principes ISO 27001) ; guide d'explication du projet.
- Purge automatique quotidienne (service `purge`), étendue aux décisions des modérateurs.
- Exercice des droits journalisé avec l'identifiant pseudonyme (preuve de traitement).
- Conteneurs sans privilèges Linux (`cap_drop`, `no-new-privileges`).

### Modifié

- **Simplification du code** pour qu'il soit explicable de bout en bout : `src/` en 3
  fichiers, une seule route `/predict`, console en 2 onglets, réentraînement à 3 règles,
  surveillance qui ouvre un ticket, CD sans déploiement automatique. Résultats du modèle
  inchangés. Voir `docs/guide_explication.md`.
- Actions GitHub en v7 ; politique Dependabot (correctifs seulement pour les
  bibliothèques Python, Python 3.11 figé dans l'image).

## [1.0.0] - 2026-10-16

Première version de Sentinel.

### Ajouté

- Générateur de données synthétiques et validation du contrat de données.
- Modèle de détection de triche v1 (gradient boosting) : précision de 94 % sur le 1 % de
  fiches le plus suspect, contre 30 % pour le tri par nombre de signalements.
- Explications de chaque prédiction en français (SHAP) et audit d'équité intégré aux
  critères d'acceptation du modèle.
- API FastAPI sécurisée : prédiction unitaire et par lot, validation d'import, décisions
  des modérateurs, droits d'accès et d'effacement RGPD, purge des données à 12 mois.
- Console de modération accessible (import, file de revue, fiche joueur, santé du modèle).
- Déploiement Docker Compose (API + Postgres) et pipelines CI/CD GitHub Actions.
