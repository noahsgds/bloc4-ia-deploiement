"""Purge des données de plus de 12 mois (RGPD : durée de conservation limitée).

Supprime les prédictions et les décisions trop anciennes. Le service "purge" de
docker-compose.yml lance ce script automatiquement une fois par jour.

Utilisation :  python -m api.purge             (365 jours par défaut)
               python -m api.purge --days 30
"""

import argparse
import os

from api.repository import InMemoryRepository, PostgresRepository

RETENTION_DAYS = 365


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge les données trop anciennes.")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS)
    days = parser.parse_args().days
    if days < 1:
        raise SystemExit("--days doit être au moins égal à 1.")
    url = os.environ.get("DATABASE_URL")
    db = PostgresRepository(url) if url else InMemoryRepository()
    db.init_schema()
    n_predictions, n_decisions = db.purge_older_than(days)
    print(f"Purge ({days} jours) : {n_predictions} prédiction(s), {n_decisions} décision(s).")


if __name__ == "__main__":
    main()
