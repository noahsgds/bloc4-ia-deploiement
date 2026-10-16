# Historique des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ;
numérotation [SemVer](https://semver.org/lang/fr/) : MAJEUR.MINEUR.CORRECTIF.

- **MAJEUR** : changement incompatible du contrat de l'API ou des données.
- **MINEUR** : nouvelle fonctionnalité compatible, ou nouveau modèle.
- **CORRECTIF** : correction sans changement de comportement attendu.

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
