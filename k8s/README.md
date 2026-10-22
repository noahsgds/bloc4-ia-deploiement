# Pourquoi pas de Kubernetes dans ce projet

L'énoncé cite un dossier `/k8s` dans la structure attendue. J'ai choisi **Docker Compose**
(`docker-compose.yml` pour le développement, `docker-compose.prod.yml` pour l'image publiée)
pour les raisons suivantes :

1. **Un seul serveur, trois services.** La base Postgres, l'API et la purge quotidienne
   tiennent sur une machine. Kubernetes sert à répartir de nombreux conteneurs sur plusieurs
   serveurs : ici, il ajouterait beaucoup de complexité sans rien apporter.
2. **Une charge modérée.** 30 000 fiches par jour, une prédiction en quelques millisecondes :
   un seul conteneur d'API suffit largement, sans mise à l'échelle automatique.
3. **Docker Compose est déjà déclaratif et versionné.** Il décrit l'état voulu (services,
   réseaux, volumes, contrôles de santé, redémarrage automatique) et la CI vérifie à chaque
   modification que l'image démarre.

**Quand Kubernetes deviendrait pertinent :** forte croissance du nombre de joueurs, besoin
de plusieurs copies de l'API derrière un répartiteur de charge ou de mises à jour sans
interruption. L'API ne garde rien en mémoire entre deux requêtes : on écrirait alors un
`Deployment` (plusieurs copies de l'API), un `Service` (adresse stable), un `Secret` (clé
d'API et mot de passe de la base) et un `CronJob` (purge quotidienne), sans changer le code.
