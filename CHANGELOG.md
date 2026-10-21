# Historique des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ;
numérotation [SemVer](https://semver.org/lang/fr/) : MAJEUR.MINEUR.CORRECTIF.

- **MAJEUR** : changement incompatible du contrat de l'API ou des données.
- **MINEUR** : nouvelle fonctionnalité compatible, ou nouveau modèle.
- **CORRECTIF** : correction sans changement de comportement attendu.

## [Non publié]

### Ajouté

- Surveillance du modèle : dérive des données (Evidently), dérive des prédictions et
  performance sur les fiches étiquetées, avec statut ok/alerte et rapport HTML.
- Workflow quotidien de surveillance qui ouvre un ticket GitHub en cas d'alerte.
- Générateur : option `--game-patch` pour simuler une mise à jour du jeu.
- CI : les tests en échec apparaissent en annotations sur la Pull Request.
- Réentraînement automatique champion / challenger, déclenché par une alerte de
  surveillance : fenêtre glissante, seuil recalé, règles de promotion (gain confirmé par
  bootstrap, faux positifs, équité, pas d'oubli), proposition du modèle en Pull Request.
- Recette des données d'entraînement de chaque modèle (reconstruction vérifiée par empreinte).
- Retour arrière : `python -m retrain.retrain --rollback <version>`.
- Documentation RGPD (registre, AIPD, procédure des droits) et sécurité (politique,
  analyse des risques, principes ISO 27001).
- Purge automatique quotidienne (service `purge`), étendue aux décisions des modérateurs.
- Exercice des droits journalisé avec l'identifiant pseudonyme (preuve de traitement).
- Conteneurs sans privilèges Linux (`cap_drop`, `no-new-privileges`).

### Modifié

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
