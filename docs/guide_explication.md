# Sentinel expliqué simplement — guide pour la soutenance

> À relire avant le jury. Pour chaque partie : **ce que c'est** (en mots simples),
> **où c'est** dans le projet, **ce que je dis**, et **les questions probables**.
> Les numéros de critères renvoient à la grille du bloc 4.

---

## 1. Le problème et la solution en 30 secondes

**Ce que je dis :** « Arena Strike produit 30 000 fiches de fin de match par jour, mais les
modérateurs n'en examinent que 300. Aujourd'hui, ils trient par nombre de signalements :
sur le 1 % qu'ils examinent, seulement 30 % sont de vrais tricheurs, car les signalements
visent aussi les très bons joueurs. Sentinel donne à chaque fiche un score de suspicion et
3 raisons en français : on passe à 94 % de vrais tricheurs dans le 1 % examiné. Le modèle
ne sanctionne jamais : c'est le modérateur qui décide. »

**Questions probables**
- *Pourquoi pas un bannissement automatique ?* L'article 22 du RGPD interdit une décision
  ayant un effet important fondée uniquement sur un traitement automatique. Et un faux
  positif bannirait un innocent.
- *Pourquoi des données synthétiques ?* Aucune source publique ne donne de bannissements
  confirmés ; l'API de Riot Games n'a pas d'étiquettes de triche et ce seraient des données
  de vrais joueurs sans base légale. Le générateur me permet aussi de simuler une dérive.

---

## 2. Les données — `src/data.py`

**Ce que c'est :** un générateur crée des joueurs (niveau, appareil, tricheur ou non), puis
simule leurs statistiques de match. Environ 3 % de tricheurs. J'ai volontairement ajouté
des pièges réalistes : des « prodiges » honnêtes très forts, la manette qui aide à viser,
l'option d'accessibilité qui ralentit les réactions.

Une fonction de **validation** vérifie chaque jeu de données (colonnes, bornes, catégories,
doublons) et s'arrête avec un message clair si quelque chose ne va pas.

**Ce que je dis :** « Les données respectent un contrat : 13 variables de jeu, des
identifiants pseudonymes, aucune donnée sensible. Deux variables, l'âge et l'option
d'accessibilité, ne sont jamais données au modèle : elles servent uniquement à vérifier
qu'il ne pénalise pas ces groupes. »

**Questions probables**
- *Que se passe-t-il si une colonne manque ?* La validation lève une erreur qui liste tous
  les problèmes ; on n'entraîne jamais sur des données fausses (test `test_data.py`).
- *La graine 42 ?* Avec la même graine, on obtient exactement les mêmes données : c'est la
  reproductibilité (critère 3.5).

---

## 3. Le modèle — `src/model.py`

**Ce que c'est :** j'entraîne deux modèles et je garde le meilleur.
- **Régression logistique** : une formule simple, facile à expliquer (référence).
- **Gradient boosting** : beaucoup de petits arbres de décision qui se corrigent les uns les
  autres ; il capte les combinaisons (précision élevée ET réaction très rapide).

Étapes : découper les données → entraîner → choisir le seuil → évaluer une seule fois sur
le test → comparer à la règle des signalements → vérifier l'équité.

**Trois idées clés à savoir expliquer :**
1. **Découpage par joueur** (60 % entraînement, 20 % validation, 20 % test) : un même
   joueur n'est jamais des deux côtés, sinon le modèle « reconnaîtrait » le joueur au lieu
   d'apprendre la triche, et les résultats seraient trop beaux.
2. **Poids équilibrés** (`class_weight="balanced"`) : les tricheurs sont rares, on leur
   donne plus de poids pour que le modèle ne réponde pas « honnête » à tout le monde.
3. **Le seuil** : le score le plus bas qui garde moins de 1 % d'honnêtes signalés à tort.
   On protège d'abord les innocents, puis on attrape le plus de tricheurs possible.

**Questions probables**
- *Pourquoi le gradient boosting ?* Meilleure PR-AUC en validation (0,59 contre 0,58). L'écart
  est faible : la régression logistique aurait été un choix défendable aussi, plus simple.
- *Pourquoi un pipeline scikit-learn ?* La préparation des données (valeurs manquantes,
  catégories) est enregistrée avec le modèle : l'API applique exactement la même.

---

## 4. Les mesures — pourquoi pas l'« accuracy »

**Ce que c'est :** avec 3 % de tricheurs, un modèle qui répond toujours « honnête » a 97 %
de bonnes réponses… et ne sert à rien. J'utilise donc :

| Mesure | En mots simples | v1 |
|---|---|---|
| Précision sur le 1 % examiné | Sur les 300 fiches regardées, combien de vrais tricheurs ? | 94 % |
| Rappel | Part des tricheurs attrapés au seuil | 57 % |
| Faux positifs | Part des honnêtes signalés à tort | 1,3 % |
| PR-AUC | Qualité du classement des tricheurs, adaptée aux classes rares (0 à 1) | 0,59 |
| ROC-AUC | Qualité globale du classement (0,5 = hasard) | 0,87 |

**Question probable** — *1,3 % de faux positifs, l'objectif était 1 % ?* Le seuil est choisi
sur la validation pour viser 1 % ; sur le test on mesure 1,3 %, dans la tolérance de 1,5 %
prévue au cahier des charges (variabilité d'un échantillon).

---

## 5. Les explications — `src/explain.py` (critères 1.5, 5.5)

**Ce que c'est :** pour chaque fiche, les 3 variables qui ont le plus pesé, en français,
comparées aux joueurs honnêtes du même rang. Exemple : « Temps de réaction : 112 ms
(honnêtes de son rang : 262 ms) — augmente le risque ».

**Image :** SHAP répartit le score entre les variables comme on partagerait équitablement
un gain entre coéquipiers selon leur contribution.

**Question probable** — *Pourquoi comparer au même rang ?* Un joueur de rang 8 est
naturellement meilleur qu'un débutant : le comparer à la moyenne le ferait paraître suspect.

---

## 6. L'équité (critère 5.5)

**Ce que c'est :** je mesure le taux d'honnêtes signalés à tort dans chaque groupe :
manette / clavier-souris, PC / console, option d'accessibilité, tranche d'âge. L'écart entre
groupes doit rester sous 2 points. Résultat v1 : 0,75 point au maximum.

**Ce que je dis :** « Le piège principal, c'est la manette qui aide à viser : un joueur
console honnête peut ressembler à un tricheur. Je le vérifie à chaque entraînement, et un
modèle non équitable n'est jamais mis en production. »

---

## 7. L'API — `api/main.py`, `api/schemas.py`, `api/repository.py`

**Ce que c'est :** un service web (FastAPI) que la console et les autres outils appellent.
- `POST /predict` : on envoie des fiches, on reçoit les scores et les raisons, triés.
- `POST /players/{id}/decisions` : la décision du modérateur est enregistrée.
- `GET` / `DELETE /players/{id}/data` : droits d'accès et d'effacement RGPD.
- Chaque prédiction est journalisée dans Postgres (traçabilité).

**Sécurité, en une phrase par point :**
- clé d'API obligatoire, lue dans une variable d'environnement, jamais dans le code ;
- chaque champ est vérifié (types, bornes) : une donnée fausse est refusée avec un message
  en français (erreur 422), et un champ non prévu (comme l'âge) aussi ;
- requêtes SQL paramétrées : impossible d'injecter du SQL ;
- si la base tombe, les modérateurs reçoivent quand même leurs scores.

**Questions probables**
- *Pourquoi FastAPI ?* Validation automatique des données et documentation `/docs` générée
  toute seule.
- *Temps de réponse ?* Moins de 200 ms exigés ; mesuré à quelques millisecondes (test).

---

## 8. La console — `api/static/console/`

**Ce que c'est :** une page web en 2 onglets : importer un CSV et voir la file de revue
triée, puis ouvrir une fiche et enregistrer sa décision.

**Ce que je dis :** « La console a été générée avec l'aide de l'IA, je le déclare dans le
README. Elle ne contient aucune intelligence : tout vient de l'API. Mon travail porte sur
l'API et le modèle. J'ai veillé à l'accessibilité : clavier, libellés, contrastes, et la
priorité n'est jamais indiquée par la seule couleur. »

---

## 9. Docker — `Dockerfile`, `docker-compose.yml`

**Ce que c'est :** une « boîte » qui contient l'API et tout ce dont elle a besoin ; elle
fonctionne pareil partout. Docker Compose démarre 3 boîtes ensemble : la base Postgres,
l'API, et la purge quotidienne des données de plus de 12 mois.

**Sécurité :** la base n'est joignable que par l'API ; les boîtes tournent sans droits
d'administrateur, en lecture seule ; les mots de passe sont dans le fichier `.env`, jamais
dans Git.

**Question probable** — *Et Kubernetes ?* Pour un seul serveur et 3 services, Compose suffit.
L'API ne garde rien en mémoire entre deux requêtes : on pourrait passer à Kubernetes sans
changer le code.

---

## 10. CI/CD — `.github/workflows/`

**Ce que c'est :** des robots GitHub qui travaillent automatiquement.
- **CI (intégration continue)** : à chaque modification, GitHub vérifie le style, lance les
  50 tests avec une vraie base Postgres, construit l'image Docker et vérifie qu'elle démarre.
  Si un test échoue, la modification est marquée en rouge et on ne la fusionne pas.
- **CD (livraison continue)** : quand je publie une version (`git tag v1.0.0`), GitHub refait
  tous les tests, publie l'image sur son registre et crée une page de version.

**Ce que je dis :** « Personne ne peut mettre en production du code qui n'a pas passé les
tests, et l'image déployée est exactement celle qui a été testée. »

**Question probable** — *Pourquoi pas de déploiement automatique ?* Il n'y a pas de serveur de
production dans ce projet (pas de cloud payant). Le déploiement est une commande ; avec un
serveur, on ajouterait une étape au workflow.

---

## 11. La surveillance — `monitoring/monitor.py` (critères 2.3, 3.4)

**Ce que c'est :** chaque jour, deux questions.
1. **Les données ont-elles changé ?** Evidently compare les fiches récentes à un échantillon
   de référence gardé avec le modèle. Distance 0 = identique ; au-delà de 0,1 la variable
   a « dérivé ». Alerte si un quart des variables dérivent.
2. **Le modèle se trompe-t-il davantage ?** Sur les fiches dont on connaît la vérité :
   alerte si la PR-AUC baisse de plus de 0,10 ou si plus de 2 % d'honnêtes sont signalés.

En cas d'alerte, GitHub ouvre un ticket.

**Ce que je dis (la démo forte) :**
- « Après une mise à jour du jeu, tout le monde vise mieux : 4 variables dérivent et
  4,9 % d'honnêtes sont signalés. Alerte. »
- « Avec une triche humanisée, les données ne bougent pas du tout, mais la PR-AUC tombe de
  0,59 à 0,15. Seule la surveillance de la performance le voit : c'est pour ça qu'il faut
  les deux contrôles. »

**Question probable** — *Comment connaître la vérité en production ?* Par les décisions des
modérateurs. Limite : on ne la connaît que pour les fiches examinées ; il faudrait faire
examiner un petit échantillon tiré au hasard chaque jour.

---

## 12. Le réentraînement — `retrain/retrain.py` (critères 3.1, 3.2, 3.3, 3.5)

**Ce que c'est :** après une alerte, le réentraînement se lance **automatiquement** (même
workflow GitHub que la surveillance) sur les fiches récentes. L'ancien et le nouveau modèle
passent le **même examen** sur des fiches qu'aucun n'a vues. Le nouveau ne
remplace l'ancien que s'il respecte **3 règles** : meilleur, au plus 1,5 % d'honnêtes
signalés, équitable.

| Scénario | Résultat |
|---|---|
| Normal | Pas meilleur : on garde v1 |
| Patch | v1 signale 4,9 % d'honnêtes, le nouveau 0,85 % : promu en v2 |
| Triche humanisée | Promu (PR-AUC 0,22 contre 0,14) mais toujours faible |

**Ce que je dis :** « Le réentraînement corrige un jeu qui a changé. Il ne corrige pas une
triche qui ne laisse plus de trace dans mes variables : là, il faut de nouvelles données,
par exemple la trajectoire de la visée. »

**Traçabilité :** chaque version garde sa graine, l'empreinte de ses données, le commit du
code et sa version parente. Retour arrière : `python -m retrain.retrain --rollback v1`.

**Automatique, mais sous contrôle :** si le nouveau modèle passe les 3 règles, le workflow le
pousse sur une branche et ouvre une Pull Request. Un humain relit et fusionne : comme pour
les sanctions, la machine propose, l'humain valide.

**Question probable** — *Pourquoi ne pas mettre le nouveau modèle en production tout seul ?*
Un modèle qui signale à tort des joueurs a un impact direct sur eux : une validation humaine
de quelques minutes est un garde-fou peu coûteux. Techniquement, il suffirait de fusionner
automatiquement la branche.

**Question probable** — *Pourquoi seulement les fiches récentes ?* Après une mise à jour,
les anciennes statistiques décrivent un jeu qui n'existe plus.

---

## 13. RGPD — `docs/rgpd.md` (critères 5.1, 5.2)

À retenir en 6 points :
1. **Base légale** : l'intérêt légitime (parties équitables) ; les règles du jeu informent
   les joueurs des contrôles. Pas le consentement : un tricheur le retirerait.
2. **Minimisation** : identifiants pseudonymes, 13 variables de jeu, ni nom, ni e-mail, ni IP.
3. **Article 22** : un humain décide toujours, avec les raisons affichées.
4. **Droits** : accès et effacement par l'API ; effacement différé si une sanction est
   contestée (on garde les preuves) ; réponse sous un mois.
5. **Conservation** : 12 mois, purge automatique chaque jour.
6. **Analyse d'impact (AIPD)** obligatoire : notation de personnes, mineurs, grande échelle.

---

## 14. Sécurité — `docs/securite.md` (critères 5.3, 5.4)

**Ce que je dis :** « Je ne vise pas la certification ISO 27001, mais j'en applique la
démarche : une politique, une analyse de 12 risques notés, des mesures choisies en fonction
de ces risques, et des revues régulières (tests à chaque modification, surveillance
quotidienne, mises à jour hebdomadaires). »

**Limite à dire moi-même :** une seule clé d'API partagée. En production : un compte par
modérateur, avec double authentification et des rôles.

---

## 15. Les tests — `tests/` (critères 2.4, 6.x)

50 tests, un par exigence importante : données invalides refusées, découpage par joueur,
seuil, cahier des charges respecté, équité, robustesse aux valeurs manquantes, temps de
réponse, sécurité de l'API, droits RGPD, injection SQL, surveillance, réentraînement.

**Ce que je dis :** « Chaque exigence du cahier des charges a au moins un test, et la CI les
lance tous à chaque modification. »

---

## Petit glossaire

| Mot | En simple |
|---|---|
| Pipeline | Préparation des données + modèle, enregistrés ensemble |
| Faux positif | Un honnête signalé à tort |
| Rappel | Part des tricheurs qu'on attrape |
| PR-AUC | Note de 0 à 1 du classement des tricheurs, adaptée quand ils sont rares |
| SHAP | Méthode qui dit combien chaque variable a pesé dans un score |
| Dérive (drift) | Les données ou la qualité du modèle changent avec le temps |
| Evidently | Bibliothèque qui mesure la dérive et produit un rapport HTML |
| CI / CD | Robots qui testent chaque modification / publient chaque version |
| Image Docker | Boîte qui contient l'application et tout ce dont elle a besoin |
| Champion / challenger | Modèle en production / nouveau candidat |
| Pseudonyme | Identifiant qui ne révèle pas l'identité sans une table séparée |
