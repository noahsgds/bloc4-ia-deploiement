# Cahier des charges — Sentinel, détection de triche par IA

> Projet fictif réalisé dans le cadre de la certification « Architecte en Intelligence Artificielle » (RNCP, bloc 4).
> Le studio, le jeu et les données sont fictifs. Les données sont générées synthétiquement.

## 1. Contexte métier

**Nebula Forge** (studio fictif) édite **Arena Strike**, un jeu de tir tactique en 5 contre 5, gratuit, sur PC et console (comparable à Valorant ou CS2). Le jeu compte environ 200 000 joueurs actifs et est classé PEGI 16.

**Problème :**

- Les tricheurs (aimbot, wallhack) font fuir les joueurs honnêtes : baisse des revenus des achats en jeu et image dégradée.
- Environ **30 000 fiches (joueur, match)** sont produites chaque jour à la fin des parties.
- Les joueurs envoient environ **2 000 signalements par jour**, mais l'équipe de modération ne peut examiner qu'environ **300 dossiers par jour**, soit **1 %** des fiches.
- Aujourd'hui, les modérateurs examinent en priorité les joueurs les plus signalés. Or les signalements visent aussi les très bons joueurs honnêtes (adversaires frustrés) : la plupart sont infondés, et les tricheurs discrets, peu signalés, passent entre les mailles.

## 2. Objectif

Attribuer à **chaque** couple **(joueur, match)** un **score de suspicion** (entre 0 et 1, qui sert à trier ; ce n'est pas une probabilité calibrée), signalé ou non, afin de **prioriser la file de revue** des modérateurs : les 300 cas les plus suspects de la journée sont examinés en premier.

- **Définition de la cible :** `is_cheater = 1` si le compte a été banni pour triche après revue humaine. Dans les données synthétiques, la vérité est connue. En conditions réelles, ces étiquettes seraient imparfaites (des tricheurs ne sont jamais détectés).
- **Usage :** aide à la décision uniquement. **Le modèle ne bannit jamais seul.** Un modérateur valide chaque sanction (article 22 du RGPD : pas de décision fondée exclusivement sur un traitement automatisé).

## 3. Parties prenantes

| Partie prenante | Rôle |
|---|---|
| Modérateurs | Utilisent le score et les explications pour décider des sanctions |
| Équipe MLOps | Maintient, surveille et réentraîne le modèle |
| DPO | Valide la conformité RGPD |
| Joueurs | Personnes concernées ; disposent d'un droit de contestation d'un bannissement |

## 4. Données (contrat d'interface)

Une ligne par joueur et par match terminé. Le pipeline de données (bloc 3) produit exactement cette table.

| Variable | Type | Rôle |
|---|---|---|
| `player_id`, `match_id` | identifiants pseudonymisés (UUID) | clés, jamais utilisées comme features |
| `accuracy`, `headshot_rate`, `kd_ratio`, `kills_per_min`, `damage_per_round` | numérique | performance au tir |
| `avg_reaction_ms` | numérique | temps de réaction (un aimbot réagit de façon surhumaine) |
| `kills_through_smoke_ratio` | numérique | éliminations à travers la fumée (signal de wallhack) |
| `rank_tier`, `account_age_days`, `hours_played_total` | numérique / catégoriel | contexte (un très bon joueur n'est pas un tricheur) |
| `reports_received` | numérique | signalements reçus pendant le match |
| `input_device` (clavier-souris / manette), `platform` | catégoriel | contexte et audit de biais |
| `age_band` | catégoriel (tranche d'âge) | **exclu du modèle**, utilisé uniquement pour l'audit d'équité et la protection des mineurs |
| `accessibility_mode` | booléen | **réglage technique du jeu** (option de remappage ou d'entrées assistées activée dans les paramètres) ; **exclu du modèle**, utilisé uniquement pour l'audit d'équité |
| `is_cheater` | booléen | cible |

- **Source :** générateur Python synthétique, graine fixe, environ **3 % de tricheurs** (classe très minoritaire).
- **Paramètre de drift :** simulation d'une « triche humanisée » (aimbot qui rate volontairement des tirs pour ressembler à un humain).
- **Minimisation :** aucun pseudo, email, adresse IP ni message de chat. Uniquement des statistiques de jeu.
- **Aucune donnée sensible** au sens de l'article 9 du RGPD (santé, handicap, origine, opinions…) n'est collectée. Voir la section 8 pour les variables d'audit.

### Pièges d'équité identifiés

1. **Assistance à la visée :** sur console, la manette aide à viser. Un joueur console honnête peut avoir une précision élevée et ressembler à un tricheur. Le taux de faux positifs est mesuré séparément par `input_device`.
2. **Joueurs en situation de handicap :** les joueurs utilisant des manettes adaptées ou des remappages ont parfois des schémas d'input atypiques. Le taux de faux positifs est mesuré séparément pour le groupe `accessibility_mode`. La revue humaine reste obligatoire.

## 5. Métriques de succès

Les seuils ont été fixés **après une étude de faisabilité** sur les données synthétiques (5 graines aléatoires différentes), sous la plage observée et avec une marge. Une partie des tricheurs est volontairement « discrète » (triche intermittente et peu marquée), ce qui fixe un plafond réaliste aux performances.

| Type | Métrique | Seuil |
|---|---|---|
| Modèle | PR-AUC (métrique principale, classes très déséquilibrées) | ≥ 0,45 |
| Modèle | ROC-AUC | ≥ 0,80 |
| Métier | Précision sur le 1 % le plus suspect (capacité de revue quotidienne) | ≥ 80 % |
| Métier | Rappel : part des tricheurs détectés au seuil de décision | ≥ 40 % |
| Éthique | Taux de faux positifs (joueurs honnêtes signalés à tort) ; seuil de décision choisi pour le plafonner | ≤ 1 % (tolérance 1,5 % sur le test) |
| Équité | Écart de taux de faux positifs manette / clavier-souris et `accessibility_mode` / reste | < 2 points |
| Modèle | Nettement meilleur que la règle actuelle « trier par nombre de signalements » (PR-AUC au moins doublée) et que la régression logistique de référence | oui |
| Service | Latence p95 d'une prédiction | < 200 ms |

Le taux de faux positifs est retenu comme métrique d'équité car le préjudice principal est d'être **soupçonné à tort**.

## 6. Exigences fonctionnelles

- **F1** – `POST /predict` : score de triche d'un joueur sur un match, niveau de priorité, version du modèle.
- **F2** – `POST /predict/batch` : scoring d'une liste, renvoyée triée par suspicion (file de revue). Maximum 1 000 lignes par requête.
- **F3** – Explication des 3 facteurs principaux (SHAP), formulée en français clair.
- **F4** – `GET /health` et `GET /model-info` : état du service, version et métriques du modèle.
- **F5** – Journalisation de chaque prédiction (monitoring et traçabilité).
- **F6** – Rapport de drift (Evidently) comparant les données récentes aux données d'entraînement.
- **F7** – Réentraînement automatique. Le nouveau modèle n'est promu que s'il bat le modèle en place **et** respecte les seuils d'équité.

## 7. Exigences non fonctionnelles

- **Sécurité :** clé d'API (en-tête `X-API-Key`), secrets hors du code (`.env` non versionné, GitHub Secrets), validation stricte des entrées (Pydantic), conteneur exécuté sans droits root, dépendances figées.
- **Robustesse :** entrée invalide → erreur 422 explicite (jamais 500) ; valeurs manquantes imputées ; tests face aux valeurs aberrantes et catégories inconnues.
- **Maintenabilité :** code modulaire, tests automatisés (pytest), intégration continue, modèles versionnés avec leurs métadonnées (métriques, empreinte des données, graine, commit Git).
- **Évolutivité :** API sans état (plusieurs instances possibles derrière un répartiteur de charge), scoring par lot.
- **Exploitabilité :** logs structurés, démarrage complet avec `docker compose up`, vérification de santé (healthcheck) de chaque service, limites de ressources (CPU, mémoire) déclarées pour chaque conteneur.
- **Alertes :** une dérive significative ou l'échec d'un réentraînement déclenche automatiquement une alerte (ticket GitHub créé par le workflow et notification).
- **Communications :** la base de données n'est jamais exposée hors du réseau Docker interne. En production, l'API serait servie en HTTPS derrière un reverse proxy ; ce choix est documenté.
- **Traçabilité des exigences :** une matrice relie chaque exigence de ce document au code et aux tests qui la vérifient.

## 8. RGPD et loi Informatique et Libertés

- **Base légale :** exécution du contrat (les conditions d'utilisation interdisent la triche) et intérêt légitime (garantir des parties équitables).
- **Pas de bannissement automatique :** revue humaine systématique ; explication de la décision ; procédure de contestation.
- **Mineurs :** jeu PEGI 16, joueurs de 16-17 ans présents (consentement numérique à 15 ans en France). Explications compréhensibles, aucun profilage marketing à partir de ces données.
- **Droits des personnes :** `GET` et `DELETE /players/{id}/data` (accès et effacement), protégés et journalisés. Exception : les éléments justifiant un bannissement en cours de contestation sont conservés jusqu'à la fin du litige.
- **Droit de rectification :** les statistiques proviennent des serveurs de jeu. Une erreur alléguée est traitée via la procédure de contestation, qui peut aboutir à la correction ou à l'annulation des données et de la décision.
- **Conservation :** statistiques de match brutes (serveurs de jeu) 6 mois ; journal des prédictions et décisions des modérateurs 12 mois, puis purge automatique quotidienne.
- **Registre des traitements, AIPD et procédures :** détaillés dans `docs/rgpd.md` ; politique et analyse des risques de sécurité dans `docs/securite.md`.

### Variables d'audit et risque de donnée sensible par inférence

Le système ne traite **aucune donnée sensible au sens de l'article 9 du RGPD**. Deux variables demandent néanmoins une précaution particulière :

- **`accessibility_mode`** : il s'agit d'un **réglage technique** du jeu (option de remappage ou d'entrées assistées), pas d'une déclaration de handicap. Le joueur n'est jamais interrogé sur la raison de son usage. Comme un handicap pourrait en être déduit, la variable est traitée avec précaution.
- **`age_band`** : l'âge n'est pas une donnée sensible, mais il permet d'identifier les mineurs, qui bénéficient d'une protection renforcée.

Mesures appliquées à ces deux variables :

1. Jamais utilisées comme variables du modèle.
2. Absentes des logs de prédiction et des réponses de l'API.
3. Accès restreint à l'équipe chargée de l'audit d'équité.
4. Résultats d'audit publiés uniquement de façon **agrégée** (taux par groupe, jamais par joueur).

Objectif : vérifier que le modèle ne pénalise ni les joueurs utilisant des options d'accessibilité, ni les joueurs mineurs, sans créer de nouveau risque pour leur vie privée.

### Sécurité et gouvernance

- Secrets hors du code, comptes protégés par authentification à deux facteurs (GitHub), disque chiffré sur le poste d'exploitation.
- La solution ne vise pas une certification ISO 27001, mais applique ses principes : politique de sécurité documentée, analyse des risques, revue régulière. La gouvernance d'ensemble est décrite dans le plan de gouvernance de Nebula Forge.

## 9. Accessibilité

- Test d'équité obligatoire sur le groupe `accessibility_mode`.
- Console de modération (page web) respectant les bases du RGAA : labels de formulaire, contrastes suffisants, navigation au clavier, information ne reposant pas uniquement sur la couleur.
- Explications rédigées en langage clair, sans jargon.

## 10. Critères d'acceptation

| ID | Critère | Critère de la grille |
|---|---|---|
| CA-01 | Seuils de la section 5 atteints ; meilleur que la baseline et la règle actuelle | 1.2 |
| CA-02 | Robuste aux valeurs manquantes, aberrantes et catégories inconnues | 1.3 |
| CA-03 | 3 facteurs explicatifs pour chaque prédiction | 1.5, 5.5 |
| CA-04 | Erreur 422 sur entrée invalide, 401 sans clé d'API | 2.3, 2.5 |
| CA-05 | Latence p95 < 200 ms | 2.2 |
| CA-06 | Écarts de taux de faux positifs < 2 points (manette, accessibilité) | 5.5, 1.1 |
| CA-07 | CI verte à chaque push, image publiée à chaque tag | 4.1 à 4.5 |
| CA-08 | Aucun secret dans le dépôt | 4.6 |
| CA-09 | Le drift « triche humanisée » est détecté | 3.4 |
| CA-10 | Réentraînement reproductible ; promotion conditionnée à la performance et à l'équité | 3.2, 3.5 |
| CA-11 | Routes d'accès et d'effacement fonctionnelles | 5.2 |
