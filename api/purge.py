"""Purge des prédictions dépassant la durée de conservation (RGPD, minimisation).

Les logs de prédiction sont conservés 12 mois (cahier des charges, section 8), puis
supprimés. Ce script est destiné à être lancé automatiquement chaque jour.

Utilisation :
    python -m api.purge              # supprime les prédictions de plus de 365 jours
    python -m api.purge --days 30
"""

import argparse

from api.main import build_repository

RETENTION_DAYS = 365


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge les prédictions trop anciennes.")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS)
    args = parser.parse_args()
    if args.days < 1:
        raise SystemExit("--days doit être au moins égal à 1.")

    repository = build_repository()
    repository.init_schema()
    deleted = repository.purge_older_than(args.days)
    print(f"{deleted} prédiction(s) de plus de {args.days} jours supprimée(s).")


if __name__ == "__main__":
    main()
