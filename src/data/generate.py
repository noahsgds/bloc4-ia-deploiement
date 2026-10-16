"""Générateur de données synthétiques pour Sentinel.

Produit une table "une ligne = un joueur sur un match", conforme au contrat de
données du cahier des charges (section 4).

Principe : on crée d'abord des joueurs (niveau, appareil, tricheur ou non), puis
on simule leurs statistiques sur plusieurs matchs. Les tricheurs ont des
statistiques "trop bonnes" ; le paramètre ``cheat_intensity`` règle à quel point.

- cheat_intensity = 1.0 : triche classique, facile à repérer (données d'entraînement).
- cheat_intensity = 0.4 : "triche humanisée", l'aimbot rate volontairement des tirs
  pour ressembler à un humain. C'est le scénario de dérive (drift) de la démo.

Utilisation en ligne de commande :
    python -m src.data.generate --n-matches 50000 --output data/train.csv
    python -m src.data.generate --cheat-intensity 0.4 --seed 7 --output data/drift.csv
"""

import argparse
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import ALL_COLUMNS, RANDOM_SEED

# Part des joueurs tricheurs (environ 3 %, classe très minoritaire).
CHEATER_RATE = 0.03
# Part des joueurs qui utilisent l'option d'accessibilité du jeu.
ACCESSIBILITY_RATE = 0.04
# Part des temps de réaction perdus (panne de télémétrie) -> valeurs manquantes.
MISSING_REACTION_RATE = 0.02
# Nombre moyen de matchs par joueur dans un jeu de données.
MATCHES_PER_PLAYER = 6


def _new_uuid(rng: np.random.Generator) -> str:
    """Crée un identifiant unique pseudonyme, reproductible grâce au générateur aléatoire."""
    return str(uuid.UUID(bytes=rng.bytes(16), version=4))


def generate_players(n_players: int, rng: np.random.Generator) -> pd.DataFrame:
    """Crée les joueurs et leurs caractéristiques stables (identiques d'un match à l'autre)."""
    is_cheater = rng.random(n_players) < CHEATER_RATE

    # Plateforme : 70 % PC, 30 % console.
    platform = np.where(rng.random(n_players) < 0.70, "pc", "console")
    # Sur console on joue presque toujours à la manette ; sur PC, rarement.
    uses_controller = np.where(
        platform == "console",
        rng.random(n_players) < 0.95,
        rng.random(n_players) < 0.10,
    )
    input_device = np.where(uses_controller, "manette", "clavier_souris")

    # Rang de 1 (débutant) à 8 (élite), la plupart des joueurs au milieu.
    rank_tier = np.clip(np.round(rng.normal(4.5, 1.6, n_players)), 1, 8).astype(int)

    # Talent individuel : à rang égal, certains joueurs honnêtes sont nettement meilleurs.
    # 3 % de "prodiges" ont des statistiques exceptionnelles SANS tricher : le modèle
    # doit apprendre à ne pas les confondre avec des tricheurs.
    talent = rng.normal(0, 0.10, n_players) + 0.35 * (rng.random(n_players) < 0.03)

    # Chaque tricheur a son propre style :
    # - un type de triche fixe : 70 % aimbot (visée automatique),
    #   30 % wallhack (voir à travers les murs) ;
    # - une "force" de triche entre 0.3 (discret) et 1.0 (flagrant).
    cheat_type = np.where(rng.random(n_players) < 0.70, "aimbot", "wallhack")
    cheat_strength = np.where(is_cheater, rng.uniform(0.3, 1.0, n_players), 0.0)

    # Les tricheurs créent souvent de nouveaux comptes après un bannissement :
    # leurs comptes sont plus récents en moyenne (beaucoup de comptes honnêtes sont récents aussi).
    account_age_days = np.where(
        is_cheater,
        rng.exponential(150, n_players),
        rng.exponential(400, n_players),
    ).astype(int)
    account_age_days = np.clip(account_age_days, 0, 5000)

    # Heures jouées : liées à l'ancienneté du compte (environ 1 h par jour, avec du bruit).
    hours_played_total = np.clip(
        account_age_days * rng.uniform(0.3, 1.5, n_players), 1, 20000
    ).round(1)

    age_band = rng.choice(
        ["16-17", "18-24", "25-34", "35+"], size=n_players, p=[0.10, 0.45, 0.30, 0.15]
    )
    accessibility_mode = rng.random(n_players) < ACCESSIBILITY_RATE

    return pd.DataFrame(
        {
            "player_id": [_new_uuid(rng) for _ in range(n_players)],
            "is_cheater": is_cheater.astype(int),
            "platform": platform,
            "input_device": input_device,
            "rank_tier": rank_tier,
            "account_age_days": account_age_days,
            "hours_played_total": hours_played_total,
            "age_band": age_band,
            "accessibility_mode": accessibility_mode,
            # Colonnes internes à la simulation : elles ne sortent jamais du générateur
            # (dans la réalité, on ne connaît ni le talent ni le style de triche).
            "talent": talent,
            "cheat_type": cheat_type,
            "cheat_strength": cheat_strength,
        }
    )


def simulate_matches(
    players: pd.DataFrame,
    n_matches: int,
    rng: np.random.Generator,
    cheat_intensity: float,
    start_date: str,
) -> pd.DataFrame:
    """Simule les statistiques de fin de match pour des joueurs tirés au hasard.

    Chaque statistique = niveau du joueur + effet de l'appareil + effet de la triche + bruit.
    """
    # On tire au hasard quel joueur a joué chaque ligne de match.
    rows = players.iloc[rng.integers(0, len(players), n_matches)].reset_index(drop=True)
    n = len(rows)

    # Niveau : environ 0 (débutant) à 1 (élite), déduit du rang + talent individuel.
    skill = (rows["rank_tier"].to_numpy() - 1) / 7 + rows["talent"].to_numpy()
    controller = (rows["input_device"] == "manette").to_numpy()
    accessibility = rows["accessibility_mode"].to_numpy()
    cheater = rows["is_cheater"].to_numpy() == 1

    # Un tricheur n'active pas sa triche à chaque match (environ 70 % des matchs) pour
    # éviter d'être repéré. Sur les autres matchs, il joue "normalement" mais reste
    # étiqueté tricheur : c'est un bruit d'étiquette réaliste.
    cheating_now = cheater & (rng.random(n) < 0.70)
    aimbot = cheating_now & (rows["cheat_type"].to_numpy() == "aimbot")
    wallhack = cheating_now & (rows["cheat_type"].to_numpy() == "wallhack")
    # Force effective de la triche sur ce match :
    # force propre au tricheur x intensité globale (1.0 = flagrante, 0.4 = "humanisée").
    boost = rows["cheat_strength"].to_numpy() * cheat_intensity * cheating_now

    # Précision : l'assistance à la visée de la manette augmente la précision des joueurs HONNÊTES.
    # C'est le piège d'équité n°1 du cahier des charges.
    accuracy = 0.18 + 0.12 * skill + 0.05 * controller + 0.15 * boost * aimbot
    accuracy = accuracy + rng.normal(0, 0.04, n)

    # Tirs à la tête : la manette les rend plus rares, l'aimbot beaucoup plus fréquents.
    headshot_rate = 0.15 + 0.20 * skill - 0.03 * controller + 0.30 * boost * aimbot
    headshot_rate = headshot_rate + rng.normal(0, 0.06, n)

    # Temps de réaction (ms) : un aimbot réagit de façon surhumaine.
    # Les joueurs en mode accessibilité ont des temps plus longs et plus variables :
    # c'est le piège d'équité n°2 (ne pas les confondre avec des anomalies de triche).
    reaction_noise_sd = np.where(accessibility, 70, 35)
    avg_reaction_ms = (
        300 - 80 * skill + 15 * controller + 40 * accessibility - 130 * boost * aimbot
    ) + rng.normal(0, reaction_noise_sd, n)

    # Éliminations à travers la fumée : signal typique du wallhack.
    kills_through_smoke_ratio = 0.02 + 0.15 * boost * wallhack + rng.normal(0, 0.025, n)

    # Ratio éliminations/morts : loi "log-normale" (toujours positive, quelques valeurs hautes).
    kd_ratio = (0.8 + 0.6 * skill) * (1 + 0.8 * boost) * rng.lognormal(0, 0.3, n)
    kills_per_min = 0.5 + 0.4 * skill + 0.4 * boost + rng.normal(0, 0.15, n)
    damage_per_round = 100 + 60 * skill + 50 * boost + rng.normal(0, 20, n)

    # Signalements : les tricheurs en reçoivent plus, mais les très bons joueurs aussi
    # (les adversaires frustrés signalent). C'est pourquoi "trier par signalements" est une
    # mauvaise règle : elle confond talent et triche.
    reports_lambda = 0.2 + 0.4 * kd_ratio + 1.5 * boost
    reports_received = rng.poisson(reports_lambda)

    # Date du match : répartie sur 60 jours à partir de start_date.
    match_date = pd.Timestamp(start_date) + pd.to_timedelta(rng.integers(0, 60, n), unit="D")

    matches = rows.assign(
        match_id=[_new_uuid(rng) for _ in range(n)],
        match_date=match_date.date,
        accuracy=np.clip(accuracy, 0.02, 0.95).round(3),
        headshot_rate=np.clip(headshot_rate, 0.0, 1.0).round(3),
        avg_reaction_ms=np.clip(avg_reaction_ms, 80, 800).round(1),
        kills_through_smoke_ratio=np.clip(kills_through_smoke_ratio, 0.0, 1.0).round(3),
        kd_ratio=np.clip(kd_ratio, 0.0, 50.0).round(2),
        kills_per_min=np.clip(kills_per_min, 0.0, 10.0).round(2),
        damage_per_round=np.clip(damage_per_round, 0.0, 1000.0).round(1),
        reports_received=np.clip(reports_received, 0, 50),
    )

    # Perte de télémétrie : quelques temps de réaction manquants (à gérer par le modèle).
    missing = rng.random(n) < MISSING_REACTION_RATE
    matches.loc[missing, "avg_reaction_ms"] = np.nan

    return matches


def apply_game_patch(matches: pd.DataFrame) -> pd.DataFrame:
    """Simule une mise à jour du jeu ("patch 2.0") qui rend les armes plus précises.

    TOUS les joueurs, honnêtes compris, visent mieux et réagissent plus vite : la
    distribution des statistiques change (dérive des données), sans que la triche change.
    Les décalages sont fixes (aucun tirage aléatoire), donc la reproductibilité est intacte.
    """
    patched = matches.copy()
    patched["accuracy"] = (patched["accuracy"] + 0.04).clip(0.02, 0.95).round(3)
    patched["headshot_rate"] = (patched["headshot_rate"] + 0.04).clip(0.0, 1.0).round(3)
    patched["avg_reaction_ms"] = (patched["avg_reaction_ms"] - 20).clip(80, 800).round(1)
    patched["kills_per_min"] = (patched["kills_per_min"] * 1.15).clip(0.0, 10.0).round(2)
    return patched


def generate_dataset(
    n_matches: int = 50_000,
    seed: int = RANDOM_SEED,
    cheat_intensity: float = 1.0,
    start_date: str = "2026-08-01",
    game_patch: bool = False,
) -> pd.DataFrame:
    """Génère un jeu de données complet et reproductible.

    Args:
        n_matches: nombre de lignes (joueur, match) à produire.
        seed: graine aléatoire ; la même graine donne exactement les mêmes données.
        cheat_intensity: force de la triche (1.0 = flagrante, 0.4 = humanisée / drift).
        start_date: date du premier jour de la période simulée (format AAAA-MM-JJ).
        game_patch: True pour simuler une mise à jour du jeu (dérive des données).

    Returns:
        Un DataFrame avec les colonnes du contrat de données, dans l'ordre de ``ALL_COLUMNS``.
    """
    if n_matches <= 0:
        raise ValueError("n_matches doit être strictement positif.")
    if not 0.0 <= cheat_intensity <= 1.0:
        raise ValueError("cheat_intensity doit être compris entre 0 et 1.")

    rng = np.random.default_rng(seed)
    n_players = max(1, n_matches // MATCHES_PER_PLAYER)
    players = generate_players(n_players, rng)
    matches = simulate_matches(players, n_matches, rng, cheat_intensity, start_date)
    if game_patch:
        matches = apply_game_patch(matches)
    return matches[ALL_COLUMNS]


def main() -> None:
    """Point d'entrée en ligne de commande : génère un fichier CSV."""
    parser = argparse.ArgumentParser(description="Génère des données synthétiques Sentinel.")
    parser.add_argument("--n-matches", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--cheat-intensity", type=float, default=1.0)
    parser.add_argument("--start-date", default="2026-08-01")
    parser.add_argument("--game-patch", action="store_true", help="simule une mise à jour du jeu")
    parser.add_argument("--output", type=Path, default=Path("data/train.csv"))
    args = parser.parse_args()

    df = generate_dataset(
        args.n_matches, args.seed, args.cheat_intensity, args.start_date, args.game_patch
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    print(
        f"{len(df)} lignes écrites dans {args.output} "
        f"(tricheurs : {df['is_cheater'].mean():.1%}, intensité de triche : {args.cheat_intensity})"
    )


if __name__ == "__main__":
    main()
