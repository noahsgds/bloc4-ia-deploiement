# Protection des données personnelles — Sentinel

> Critères 5.1 (RGPD), 5.2 (loi Informatique et Libertés) et 5.5 (IA éthique) du bloc 4.
> Nebula Forge, Arena Strike et les joueurs sont fictifs ; les données du projet sont
> synthétiques. Ce document décrit le traitement **tel qu'il serait mis en production**.
> La gouvernance d'ensemble (organisation, DPO, comité) relève du plan de gouvernance
> de Nebula Forge (bloc 1).

## 1. Fiche du registre des traitements (article 30 du RGPD)

| Rubrique | Contenu |
|---|---|
| Nom du traitement | Sentinel : priorisation des dossiers de triche pour la modération d'Arena Strike |
| Responsable de traitement | Nebula Forge (éditeur du jeu) |
| Délégué à la protection des données | DPO de Nebula Forge (contact : dpo@nebulaforge.example) |
| Finalité | Classer chaque jour les fiches (joueur, match) par niveau de suspicion pour que les modérateurs examinent d'abord les plus suspectes. **Aucune autre finalité** : ni marketing, ni profilage commercial, ni évaluation du niveau de jeu. |
| Base légale | Exécution du contrat (art. 6.1.b) : les conditions d'utilisation interdisent la triche et prévoient des contrôles. Intérêt légitime (art. 6.1.f) : garantir des parties équitables aux autres joueurs (mise en balance en section 3). |
| Personnes concernées | Joueurs d'Arena Strike (PEGI 16), **dont des mineurs de 16 et 17 ans** |
| Catégories de données | Identifiants pseudonymes (UUID joueur et match) ; statistiques de jeu par match ; contexte du compte (rang, ancienneté, heures jouées) ; signalements reçus ; appareil et plateforme ; tranche d'âge et réglage d'accessibilité (audit seulement, voir section 2) ; score de suspicion, version du modèle ; décision du modérateur. |
| Données exclues | Nom, pseudo, e-mail, adresse IP, messages du chat, voix, données de paiement, localisation. Aucune donnée sensible au sens de l'article 9. |
| Destinataires | Modérateurs (file de revue et fiches) ; équipe MLOps (surveillance, réentraînement) ; équipe d'audit d'équité (résultats agrégés seulement). Aucun destinataire externe. |
| Sous-traitants | Hébergement de production (dans l'UE) ; GitHub héberge le **code** et les modèles, jamais de données de joueurs (les tests et la CI utilisent des données synthétiques). |
| Transferts hors UE | Aucun transfert de données de joueurs. |
| Durées de conservation | Statistiques de match brutes (serveurs de jeu, bloc 3) : 6 mois. Journal des prédictions (score, statistiques utilisées, version du modèle) et décisions des modérateurs : **12 mois**, puis purge automatique quotidienne (`api/purge.py`, service `purge` de Docker Compose). Exception : dossier d'une sanction contestée, conservé jusqu'à la fin de la procédure. |
| Mesures de sécurité | Voir `docs/securite.md` : clé d'API, base non exposée, conteneurs durcis, secrets hors du code, sauvegardes chiffrées, journalisation, revue des dépendances. |
| AIPD | Requise et réalisée (section 6). |
| Date de la fiche | 21/10/2026 (revue annuelle, ou à chaque changement de finalité, de données ou de modèle) |

## 2. Minimisation et pseudonymisation

- **Pseudonymisation** : le modèle et l'API ne connaissent que des UUID. La table de
  correspondance UUID ↔ compte reste dans le système des comptes du jeu, hors de Sentinel.
- **Minimisation** : 13 variables, toutes justifiées par la détection (contrat de données,
  cahier des charges section 4). L'API refuse tout champ supplémentaire (`extra="forbid"`
  dans `api/schemas.py`) : on ne peut pas lui envoyer de données non prévues.
- **Variables d'audit** (`age_band`, `accessibility_mode`) : jamais utilisées par le
  modèle, absentes de l'API et des journaux, utilisées uniquement pour mesurer l'équité,
  résultats publiés de façon agrégée. `accessibility_mode` est un réglage technique du
  jeu, pas une déclaration de handicap : le joueur n'est jamais interrogé sur sa raison.
- **Données synthétiques** pour tout le développement, les tests et la démonstration.

## 3. Pourquoi pas le consentement, et comment les joueurs sont informés

Le consentement n'est pas la bonne base légale : il doit être libre et retirable à tout
moment. Or un joueur ne peut pas « refuser » la lutte anti-triche tout en jouant en ligne,
et un tricheur retirerait son consentement. Le traitement repose donc sur le contrat et
l'intérêt légitime.

**Mise en balance de l'intérêt légitime** : l'intérêt (parties équitables pour 200 000
joueurs) est réel ; l'atteinte est limitée (statistiques de jeu pseudonymes, aucune donnée
sensible, aucune décision automatique, conservation courte) ; le traitement est attendu
par les joueurs (annoncé dans les conditions d'utilisation, pratique courante du secteur).

**Information (articles 13 et 14)** : la politique de confidentialité du jeu indique
l'existence de Sentinel, les données utilisées, la finalité, la revue humaine, les durées
et les droits, en langage clair adapté aux joueurs de 16 ans.

## 4. Pas de décision entièrement automatisée (article 22)

- Le modèle **classe** des dossiers ; il ne sanctionne jamais. Chaque sanction est décidée
  par un modérateur, enregistrée avec son identifiant (`POST /players/{id}/decisions`).
- Le modérateur voit les **trois raisons principales** du score, en français (SHAP), et
  les statistiques du match : il peut juger le dossier, pas seulement suivre un chiffre.
- Le score est un **score de suspicion pour trier**, pas une probabilité ni une preuve.
- Le joueur sanctionné peut **contester** ; un autre modérateur réexamine le dossier.
- Le réentraînement est lancé par une personne après une alerte, et un nouveau modèle
  n'arrive en production qu'à la publication d'une version : jamais automatiquement.

## 5. Droits des personnes (loi Informatique et Libertés, articles 15 à 21 du RGPD)

**Procédure** : le joueur écrit au support ou au DPO → son identité est vérifiée par le
système des comptes, qui fournit son UUID → un opérateur habilité exécute la demande →
réponse sous **un mois** (prolongeable de deux mois si complexe, avec information).
Chaque exercice est journalisé avec l'identifiant pseudonyme et le résultat, pour prouver
que la demande a été traitée (principe de responsabilité, article 5.2).

| Droit | Mise en œuvre | Exceptions |
|---|---|---|
| Accès (art. 15) | `GET /players/{id}/data` : toutes les prédictions (score, statistiques, version du modèle, date) et décisions | — |
| Portabilité (art. 20) | Même réponse, en JSON (format structuré et lisible par machine) | — |
| Rectification (art. 16) | Les statistiques viennent des serveurs de jeu : une erreur alléguée est traitée par la procédure de contestation, qui peut corriger ou annuler les données et la décision | — |
| Effacement (art. 17) | `DELETE /players/{id}/data` : supprime prédictions et décisions | Sanction pour triche confirmée : conservation jusqu'à la fin de la contestation (art. 17.3.e, défense de droits en justice) ; l'API répond 409 et l'explique |
| Opposition (art. 21) | Examinée au cas par cas par le DPO ; l'intérêt légitime peut prévaloir (motifs impérieux : équité pour tous les joueurs) | La réponse est motivée |
| Limitation (art. 18) | Pendant une contestation, le dossier est gelé (aucune nouvelle sanction sur ces éléments) | — |
| Intervention humaine et contestation (art. 22.3) | Revue humaine systématique, contestation auprès d'un second modérateur | — |

Tests automatisés : accès, effacement, refus pendant une contestation, purge à 12 mois
(`tests/test_api.py`, `tests/test_repository.py`).

## 6. Analyse d'impact (AIPD) — synthèse

**Pourquoi elle est obligatoire** : la liste de la CNIL demande une AIPD dès que deux
critères sont réunis. Ici : évaluation et notation de personnes (score), personnes
vulnérables (mineurs), traitement à grande échelle (30 000 fiches par jour), décision
ayant un effet important (bannissement, même décidé par un humain).

| Risque pour les joueurs | Gravité | Mesures | Risque résiduel |
|---|---|---|---|
| Bannissement injuste d'un joueur honnête (très bon, sur console, utilisant l'accessibilité) | Importante | Revue humaine, raisons affichées, faux positifs ≤ 1 % en acceptation, audit d'équité par groupe (écart < 2 points), contestation | Limité |
| Discrimination indirecte (handicap déduit, âge) | Importante | Variables d'audit exclues du modèle et de l'API, résultats agrégés, audit à chaque réentraînement (règle de promotion) | Limité |
| Dérive du modèle qui accuse des innocents (mise à jour du jeu) | Importante | Surveillance quotidienne des faux positifs, alerte, réentraînement contrôlé | Limité |
| Accès non autorisé ou fuite des données | Moyenne (données pseudonymes) | Voir `docs/securite.md` | Limité |
| Conservation excessive | Moyenne | Purge automatique à 12 mois, testée | Négligeable |
| Détournement de finalité (marketing, profilage) | Moyenne | Finalité unique inscrite au registre, aucun export prévu, accès restreint | Limité |

Conclusion : le traitement peut être mis en œuvre avec ces mesures. L'AIPD est revue à
chaque changement de modèle significatif (nouvelles variables) ou de finalité.

## 7. Mineurs

- Jeu PEGI 16 : des joueurs de 16 et 17 ans sont concernés. En France, l'âge du
  consentement numérique est de 15 ans, mais le traitement ne repose pas sur le
  consentement (section 3).
- Protection renforcée : aucun profilage marketing, explications en langage simple,
  audit d'équité spécifique sur la tranche d'âge, accompagnement de la contestation.
- La tranche d'âge n'apparaît jamais dans l'API ni dans les journaux.

## 8. Violation de données

1. Détection (journaux, alerte) → information immédiate du DPO.
2. Confinement : révocation de la clé d'API (rotation du secret), arrêt du service si besoin.
3. Notification à la CNIL **sous 72 heures** si la violation présente un risque pour les
   joueurs ; information des joueurs si le risque est élevé.
4. Registre des violations tenu par le DPO, même pour les incidents non notifiés.

## 9. IA éthique (critère 5.5)

| Principe | Mise en œuvre |
|---|---|
| Explicabilité | Trois raisons en français par prédiction (SHAP), notebook 03, console |
| Justesse | Métriques adaptées à la classe rare (PR-AUC, précision sur le 1 % examiné), seuils d'acceptation |
| Non-discrimination | Audit des faux positifs par appareil, plateforme, accessibilité et âge ; bloquant à l'acceptation et à chaque réentraînement |
| Contrôle humain | Aucune sanction automatique, aucune mise en production de modèle sans validation |
| Vie privée | Pseudonymisation, minimisation, conservation limitée, données synthétiques en développement |
| Transparence sur les limites | Score de suspicion non calibré ; triche « humanisée » mal détectée (documenté) |

## 10. Limites connues

- Démonstration avec une seule clé d'API partagée : en production, comptes individuels
  pour les modérateurs (authentification unique de l'entreprise avec double facteur) et
  droits différenciés (le droit d'effacement réservé à un rôle « DPO »). Voir `docs/securite.md`.
- La procédure de contestation et la politique de confidentialité sont décrites ici,
  pas outillées (hors périmètre du bloc 4, relèvent du bloc 1).
