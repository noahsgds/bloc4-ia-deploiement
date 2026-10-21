# Sécurité de l'information — Sentinel

> Critères 5.3 (normes de sécurité) et 5.4 (ISO 27001) du bloc 4.
> Sentinel ne vise pas une certification ISO 27001 (projet d'une personne, sans
> organisation à certifier) mais en applique la démarche : une politique, une analyse
> des risques, des mesures choisies en fonction des risques, des revues régulières.
> Le système de management de la sécurité de Nebula Forge est décrit dans le bloc 1.

## 1. Politique de sécurité

**Objectifs (confidentialité, intégrité, disponibilité)**

- **Confidentialité** : seules les personnes habilitées voient les scores et les fiches ;
  aucune donnée de joueur ne quitte l'infrastructure de production.
- **Intégrité** : le modèle en production est exactement celui qui a été testé et validé ;
  les données d'entraînement sont vérifiables (empreinte) ; les décisions sont tracées.
- **Disponibilité** : la file de revue reste utilisable même si la base de journalisation
  tombe (la prédiction est renvoyée, l'incident est journalisé).

**Règles**

1. Aucun secret dans le code ni dans Git : `.env` local (ignoré par Git), secrets GitHub en CI/CD.
2. Moindre privilège partout : clé d'API obligatoire, base non exposée, conteneurs sans
   privilèges, workflows GitHub avec des droits déclarés job par job.
3. Toute modification passe par une Pull Request testée automatiquement (CI).
4. Toute mise en production (code ou modèle) est validée par un humain.
5. Dépendances figées et surveillées chaque semaine.
6. Comptes protégés par double authentification (GitHub) ; disque du poste d'exploitation
   chiffré (FileVault) — exigé en production, non activé sur le poste de démonstration.

## 2. Analyse des risques

Échelle : vraisemblance et impact de 1 (faible) à 3 (fort) ; risque = V × I.

| # | Menace | V | I | Risque | Mesures en place | Résiduel |
|---|---|---|---|---|---|---|
| R1 | Vol ou fuite de la clé d'API | 2 | 3 | 6 | Clé hors du code, refus de démarrer avec une clé vide ou « change-me », comparaison en temps constant, rotation documentée | 3 |
| R2 | Injection SQL ou données malformées | 2 | 3 | 6 | Requêtes SQL paramétrées (test d'injection), validation stricte Pydantic (bornes, champs inconnus refusés), lots limités à 1 000 | 2 |
| R3 | Script malveillant dans la console (XSS) | 1 | 2 | 2 | CSP stricte (aucune ressource externe, aucun script injecté), aucun contenu HTML inséré depuis les données | 1 |
| R4 | Accès direct à la base | 2 | 3 | 6 | Postgres sans port publié (réseau Docker interne), mot de passe fort en secret | 2 |
| R5 | Compromission d'un conteneur | 1 | 3 | 3 | Utilisateur non root, système de fichiers en lecture seule, aucun privilège Linux (`cap_drop: ALL`), `no-new-privileges`, limites CPU et mémoire | 1 |
| R6 | Dépendance vulnérable (chaîne d'approvisionnement) | 2 | 3 | 6 | Versions figées, Dependabot hebdomadaire, alertes de sécurité GitHub, CI avant toute fusion | 3 |
| R7 | Compte GitHub piraté (code ou modèle modifié) | 1 | 3 | 3 | Double authentification, dépôt privé, PR obligatoire, CD sur tag seulement | 2 |
| R8 | Vol du poste d'exploitation | 1 | 3 | 3 | Données synthétiques et pseudonymes, secrets hors du dépôt ; en production : disque chiffré (FileVault) | 2 |
| R9 | Perte de données (panne, erreur) | 2 | 2 | 4 | Volume Docker persistant, sauvegarde quotidienne chiffrée (procédure en section 4) | 2 |
| R10 | Empoisonnement des étiquettes (décisions erronées utilisées pour réentraîner) | 2 | 2 | 4 | Promotion seulement si meilleur sur des fiches jamais vues, audit d'équité, validation humaine | 2 |
| R11 | Contournement du modèle par les tricheurs | 3 | 2 | 6 | Surveillance quotidienne de la performance, alerte, réentraînement ; limite documentée (triche humanisée) | 4 |
| R12 | Interception du trafic | 2 | 2 | 4 | Démonstration en local ; en production, HTTPS via un proxy inverse et accès par VPN | 2 |

Les risques résiduels supérieurs ou égaux à 3 (R1, R6, R11) sont acceptés et suivis à
chaque revue.

## 3. Mesures, rangées selon les thèmes de l'annexe A d'ISO 27001

| Thème | Mesures |
|---|---|
| Organisationnel | Politique (section 1), analyse des risques (section 2), registre des traitements et AIPD (`docs/rgpd.md`), gestion des incidents (violation : notification CNIL sous 72 h) |
| Humain | Accès réservé aux modérateurs et à l'équipe MLOps ; sensibilisation au rôle de la revue humaine |
| Physique | Verrouillage de session ; disque chiffré exigé en production |
| Technologique | Authentification par clé, double authentification GitHub, base non exposée, conteneurs durcis, validation des entrées, SQL paramétré, CSP, journaux JSON, dépendances figées et surveillées, CI/CD avec permissions minimales, image testée = image déployée, sauvegardes |

**Chiffrement**

- Au repos : sauvegardes chiffrées ; en production, disque du serveur chiffré. Le poste de
  démonstration n'est pas chiffré : acceptable car il ne contient que des données synthétiques.
- En transit : en local, le trafic ne quitte pas la machine ; en production, HTTPS
  obligatoire (proxy inverse) et console accessible uniquement par VPN.
- Secrets : stockés chiffrés par GitHub (secrets du dépôt), jamais affichés dans les journaux.

## 4. Procédures

**Rotation de la clé d'API** (au moins tous les 6 mois, immédiatement en cas de doute) :
```bash
NEW_KEY=$(openssl rand -hex 32)
sed -i '' "s/^API_KEY=.*/API_KEY=${NEW_KEY}/" .env   # macOS
docker compose up -d                                  # l'API redémarre avec la nouvelle clé
```

**Sauvegarde de la base** (quotidienne, conservée 30 jours, chiffrée) :
```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip | openssl enc -aes-256-cbc -pbkdf2 -out "sauvegarde-$(date +%F).sql.gz.enc"
```
Restauration testée une fois par trimestre (la purge à 12 mois s'applique aussi aux
sauvegardes : on ne garde pas de sauvegarde au-delà de 30 jours).

## 5. Revues régulières (amélioration continue)

| Fréquence | Revue | Outil |
|---|---|---|
| Chaque PR | Tests, style, construction de l'image | CI GitHub Actions |
| Chaque jour | Dérive et performance du modèle, purge des données de plus de 12 mois | `monitoring.yml`, service `purge` |
| Chaque semaine | Mises à jour et vulnérabilités des dépendances | Dependabot |
| Chaque trimestre | Revue des accès (qui a la clé, comptes GitHub), test de restauration | Manuel |
| Chaque année | Revue de cette analyse de risques, du registre et de l'AIPD | Manuel, avec le DPO |

## 6. Limites et cible en production

| Aujourd'hui (démonstration) | Cible en production |
|---|---|
| Une clé d'API partagée | Comptes individuels via l'authentification unique de l'entreprise, avec double facteur, et rôles (modérateur, DPO, MLOps) |
| HTTP en local | HTTPS + VPN |
| Sauvegarde décrite, non automatisée | Sauvegarde planifiée et supervisée |
| Poste de démonstration non chiffré (données synthétiques uniquement) | Disque chiffré sur tout poste ou serveur qui traite des données réelles |
| Journaux dans la sortie des conteneurs | Centralisation et alerte (supervision Grafana, bloc 2) |
