# Fiche du modèle — Sentinel v1

> Format inspiré des « model cards » (Mitchell et al., 2019) : ce que fait le modèle, sur
> quelles données, avec quels résultats et quelles limites. Critères 1.2, 1.5 et 5.5.

| Rubrique | Contenu |
|---|---|
| Nom et version | Sentinel `v1` — `models/cheat_model_v1.joblib`, fiche technique `cheat_model_v1.json` |
| Type | Gradient boosting (`HistGradientBoostingClassifier`, scikit-learn 1.9.1), poids équilibrés |
| Préparation | Médiane pour les valeurs manquantes, encodage des catégories (valeur inconnue ignorée) |
| Entrée | 13 variables de jeu d'une fiche (joueur, match) : précision, tirs à la tête, ratio éliminations / morts, éliminations par minute, dégâts, temps de réaction, éliminations à travers la fumée, rang, ancienneté, heures de jeu, signalements, périphérique, plateforme |
| Sortie | Score de suspicion entre 0 et 1 (pour **trier**, pas une probabilité), priorité, 3 raisons |
| Seuil | 0,692 : le plus bas qui garde au plus 1 % d'honnêtes signalés en validation |
| Usage prévu | Prioriser les 300 fiches examinées chaque jour par les modérateurs |
| Usages exclus | Sanction automatique ; évaluation du niveau de jeu ; profilage commercial ; toute autre finalité |

## Données d'entraînement

- 50 000 fiches synthétiques (graine 42), août-septembre 2026, environ 3 % de tricheurs.
- Découpage par joueur : 60 % entraînement, 20 % validation (choix du modèle et du seuil),
  20 % test (évaluation finale unique).
- Empreinte des données et commit du code enregistrés dans la fiche JSON.

## Résultats (test, 9 997 fiches jamais vues)

| Mesure | v1 | Règle des signalements | Objectif |
|---|---|---|---|
| PR-AUC | 0,59 | 0,11 | ≥ 0,45 |
| ROC-AUC | 0,87 | 0,68 | ≥ 0,80 |
| Vrais tricheurs dans le 1 % examiné | 94 % | 30 % | ≥ 80 % |
| Tricheurs détectés au seuil (rappel) | 57 % | 10 % | ≥ 40 % |
| Honnêtes signalés à tort | 1,3 % | 0,6 % | ≤ 1 % (tolérance 1,5 %) |

Modèle comparé : régression logistique, PR-AUC 0,58 en validation (gradient boosting : 0,59).

## Équité (taux d'honnêtes signalés à tort par groupe)

| Groupe | Taux | Écart |
|---|---|---|
| Clavier-souris / manette | 1,53 % / 0,85 % | 0,68 point |
| PC / console | 1,46 % / 0,90 % | 0,56 point |
| Sans / avec option d'accessibilité | 1,31 % / 0,99 % | 0,32 point |
| Tranches d'âge (16-17 à 35+) | 0,77 % à 1,52 % | 0,75 point |

Tous les écarts sont sous la limite de 2 points. Les petits groupes (16-17 ans, accessibilité)
donnent des taux moins précis.

## Limites connues

1. **Données synthétiques** : les résultats valident la méthode, pas la performance réelle.
2. **Triche humanisée** : si la triche imite un humain, la PR-AUC tombe à 0,15 ; le
   réentraînement ne suffit pas, il faudrait de nouvelles variables (trajectoire de visée).
3. **Mise à jour du jeu** : sans réentraînement, 4,9 % d'honnêtes signalés à tort.
4. **Étiquettes imparfaites** en production : la vérité vient des enquêtes des modérateurs,
   seulement sur les fiches examinées.
5. **Score non calibré** : ne jamais le présenter comme un pourcentage de chances de tricher.

## Garde-fous

Décision humaine obligatoire, 3 raisons affichées, contestation possible, surveillance
quotidienne, réentraînement soumis à 3 règles (meilleur, ≤ 1,5 % de faux positifs, équitable).
