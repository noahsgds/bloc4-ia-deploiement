"""Purge des données dépassant la durée de conservation (RGPD, limitation de conservation).

Prédictions et décisions des modérateurs sont conservées 12 mois (cahier des charges,
section 8 ; docs/rgpd.md), puis supprimées. Le service "purge" de docker-compose.yml
lance ce script automatiquement une fois par jour.

Utilisation :
    python -m api.purge              # supprime les prédictions de plus de 365 jours
    python -m api.purge --days 30
"""

import argparse

from api.main import build_repository

RETENTION_DAYS = 365


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge les données trop anciennes.")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS)
    args = parser.parse_args()
    if args.days < 1:
        raise SystemExit("--days doit être au moins égal à 1.")

    repository = build_repository()
    repository.init_schema()
    n_pred, n_dec = repository.purge_older_than(args.days)
    print(
        f"Purge ({args.days} jours) : {n_pred} prédiction(s) et {n_dec} décision(s) supprimée(s)."
    )


if __name__ == "__main__":
    main()
