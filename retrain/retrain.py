"""Réentraînement automatique et promotion contrôlée (étape 10) — critères 3.1 à 3.5 du bloc 4.

Principe "champion / challenger" :
1. on entraîne un nouveau modèle (challenger) sur une fenêtre glissante : anciennes
   données + nouvelles fiches étiquetées par les modérateurs ;
2. on examine le champion (modèle en production) et le challenger sur les MÊMES fiches,
   qu'aucun des deux n'a vues : des fiches récentes et l'ancien jeu de test ;
3. le challenger n'est promu que s'il passe TOUTES les règles (meilleur, sans plus de
   faux positifs, équitable, sans oublier les anciennes triches) ;
4. s'il est promu, il est enregistré avec sa recette de données et son rapport ; la
   mise en production passe ensuite par une Pull Request validée par un humain.

Utilisation :
    python -m retrain.retrain --scenario patch            # simule l'arrivée de fiches
    python -m retrain.retrain --current fiches.csv        # export réel de fiches étiquetées
    python -m retrain.retrain --scenario patch --dry-run  # décider sans rien enregistrer
    python -m retrain.retrain --rollback v1               # revenir à une version précédente
"""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from src.config import (
    ACCEPTANCE_THRESHOLDS,
    CATEGORICAL_FEATURES,
    MAX_FALSE_POSITIVE_RATE,
    MODELS_DIR,
    NUMERIC_FEATURES,
    PROMOTION_BOOTSTRAP_DRAWS,
    PROMOTION_CONFIDENCE,
    PROMOTION_MAX_FPR,
    PROMOTION_MAX_LOSS,
    PROMOTION_MAX_OLD_LOSS,
    RANDOM_SEED,
    RECENT_CALIBRATION_SHARE,
    RECENT_TRAIN_SHARE,
    RETRAIN_REPORTS_DIR,
    REVIEW_SHARE,
    TARGET,
    TRAINING_WINDOW,
)
from src.data.validate import validate_dataset
from src.evaluate import compute_metrics, threshold_for_max_fpr
from src.fairness import fairness_passed, fairness_report
from src.lineage import (
    load_source,
    load_training_data,
    old_pool_and_test,
    recent_window,
    recipe_of,
    split_recent,
)
from src.train import (
    check_acceptance,
    data_fingerprint,
    load_champion,
    save_model,
    set_champion,
    train_and_select,
)

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


# --- Règles de décision (logique pure, testée seule) ------------------------------------


def promotion_decision(champion: dict, challenger: dict, gain_share: float) -> dict:
    """Décide si le challenger remplace le champion.

    Args:
        champion, challenger: pour chaque modèle, ``recent`` et ``old`` (métriques sur les
            fiches récentes et sur l'ancien test) et ``fairness_ok`` (audit d'équité).
        gain_share: part des tirages aléatoires où le challenger a une meilleure PR-AUC
            (voir ``bootstrap_gain_share``).

    Returns:
        {"promote": bool, "checks": {règle: bool}, "reasons": [explications en français]}
    """
    gain = challenger["recent"]["pr_auc"] - champion["recent"]["pr_auc"]
    old_loss = champion["old"]["pr_auc"] - challenger["old"]["pr_auc"]
    champion_fpr = champion["recent"]["false_positive_rate"]
    fixes_false_positives = champion_fpr > PROMOTION_MAX_FPR
    # Si le champion accuse trop d'innocents, protéger les joueurs passe en premier :
    # on accepte une petite perte de PR-AUC (même tolérance que pour l'"oubli").
    max_loss = PROMOTION_MAX_OLD_LOSS if fixes_false_positives else PROMOTION_MAX_LOSS

    checks = {
        "apporte_un_gain": gain_share >= PROMOTION_CONFIDENCE or fixes_false_positives,
        "pas_de_perte_recente": gain >= -max_loss,
        "pas_d_oubli": old_loss <= PROMOTION_MAX_OLD_LOSS,
        "faux_positifs_recents": challenger["recent"]["false_positive_rate"] <= PROMOTION_MAX_FPR,
        "faux_positifs_anciens": challenger["old"]["false_positive_rate"] <= PROMOTION_MAX_FPR,
        "equite": challenger["fairness_ok"],
    }
    labels = {
        "apporte_un_gain": (
            f"gain de PR-AUC {gain:+.3f}, confirmé dans {gain_share:.0%} des tirages "
            f"(minimum {PROMOTION_CONFIDENCE:.0%}), ou correction des faux positifs "
            f"du champion ({champion_fpr:.1%})"
        ),
        "pas_de_perte_recente": f"PR-AUC récente {gain:+.3f} (perte maximale {max_loss})",
        "pas_d_oubli": (
            f"PR-AUC sur l'ancien test {-old_loss:+.3f} (perte maximale {PROMOTION_MAX_OLD_LOSS})"
        ),
        "faux_positifs_recents": (
            f"faux positifs récents {challenger['recent']['false_positive_rate']:.1%} "
            f"(maximum {PROMOTION_MAX_FPR:.1%})"
        ),
        "faux_positifs_anciens": (
            f"faux positifs sur l'ancien test {challenger['old']['false_positive_rate']:.1%} "
            f"(maximum {PROMOTION_MAX_FPR:.1%})"
        ),
        "equite": "écart de faux positifs entre groupes inférieur à 2 points",
    }
    reasons = [("OK  " if ok else "NON ") + labels[name] for name, ok in checks.items()]
    return {"promote": all(checks.values()), "checks": checks, "reasons": reasons}


def meets_specification(metrics: dict) -> bool:
    """Le modèle atteint-il les seuils absolus du cahier des charges (section 5) ?"""
    return all(metrics[name] >= minimum for name, minimum in ACCEPTANCE_THRESHOLDS.items())


def next_version(models_dir: Path) -> str:
    """Numéro de la prochaine version : v1, v2… (jamais de réutilisation d'un numéro)."""
    numbers = [
        int(m.group(1))
        for p in models_dir.glob("cheat_model_v*.json")
        if (m := re.fullmatch(r"cheat_model_v(\d+)\.json", p.name))
    ]
    return f"v{max(numbers, default=0) + 1}"


# --- Évaluation -------------------------------------------------------------------------


def bootstrap_gain_share(
    y: np.ndarray,
    champion_scores: np.ndarray,
    challenger_scores: np.ndarray,
    players: np.ndarray,
    seed: int,
    draws: int = PROMOTION_BOOTSTRAP_DRAWS,
) -> float:
    """Part des tirages où le challenger a une meilleure PR-AUC que le champion.

    Méthode du "bootstrap" : on refait l'examen 200 fois sur un échantillon de joueurs
    tiré au hasard avec remise (un joueur peut sortir deux fois, un autre jamais). On tire
    des JOUEURS, pas des lignes, car les matchs d'un même joueur se ressemblent. Si le
    challenger gagne dans 95 % des tirages, son avance n'est pas due au hasard.
    """
    rng = np.random.default_rng(seed)
    unique_players, player_index = np.unique(players, return_inverse=True)
    rows_of = [np.flatnonzero(player_index == i) for i in range(len(unique_players))]
    wins = 0
    for _ in range(draws):
        picked = rng.integers(0, len(unique_players), size=len(unique_players))
        rows = np.concatenate([rows_of[i] for i in picked])
        if y[rows].sum() == 0:  # échantillon sans tricheur : PR-AUC non définie
            continue
        champion_ap = average_precision_score(y[rows], champion_scores[rows])
        challenger_ap = average_precision_score(y[rows], challenger_scores[rows])
        wins += challenger_ap > champion_ap
    return wins / draws


def evaluate(model, threshold: float, recent: pd.DataFrame, old: pd.DataFrame) -> dict:
    """Mesure un modèle sur les fiches récentes et sur l'ancien test, avec son propre seuil."""
    recent_scores = model.predict_proba(recent[FEATURES])[:, 1]
    old_scores = model.predict_proba(old[FEATURES])[:, 1]
    fairness = fairness_report(recent, recent_scores, threshold)
    return {
        "recent": compute_metrics(recent[TARGET], recent_scores, threshold, REVIEW_SHARE),
        "old": compute_metrics(old[TARGET], old_scores, threshold, REVIEW_SHARE),
        "fairness": {group: round(r["fpr_gap"], 4) for group, r in fairness.items()},
        "fairness_ok": fairness_passed(fairness),
    }


# --- Réentraînement ---------------------------------------------------------------------


def retrain(
    recent: pd.DataFrame,
    source: dict,
    models_dir: Path = MODELS_DIR,
    reports_dir: Path = RETRAIN_REPORTS_DIR,
    seed: int = RANDOM_SEED,
    dry_run: bool = False,
) -> dict:
    """Entraîne un challenger, le compare au champion et le promeut si les règles passent.

    Args:
        recent: nouvelles fiches étiquetées (vérité connue après enquête).
        source: description de ``recent`` pour la recette (scénario ou fichier + empreinte).
        dry_run: True pour décider sans rien enregistrer.
    """
    started = time.perf_counter()
    validate_dataset(recent)  # format modifié ou valeurs aberrantes : arrêt immédiat
    if recent[TARGET].isna().any():
        raise ValueError("Des fiches récentes n'ont pas d'étiquette (enquête non terminée).")

    champion, champion_meta = load_champion(models_dir)
    old = load_training_data(champion_meta)
    old_pool, old_test = old_pool_and_test(old, seed)
    old_test = old_test[~old_test["player_id"].isin(recent["player_id"])]  # aucun joueur vu
    # Fenêtre glissante : anciennes données + nouvelles fiches, les plus récentes d'abord.
    window, recent_rest = recent_window(old_pool, recent, seed, RECENT_TRAIN_SHARE, TRAINING_WINDOW)
    calibration_share = RECENT_CALIBRATION_SHARE / (1 - RECENT_TRAIN_SHARE)
    recent_holdout, recent_calibration = split_recent(recent_rest, seed, calibration_share)

    np.random.seed(seed)
    result = train_and_select(window, seed=seed)

    # Seuil recalé sur des fiches récentes non utilisées pour l'entraînement : il reflète
    # l'état actuel du jeu (après un patch, les honnêtes ont des scores plus élevés).
    calibration_scores = result.model.predict_proba(recent_calibration[FEATURES])[:, 1]
    result.threshold = threshold_for_max_fpr(
        recent_calibration[TARGET], calibration_scores, MAX_FALSE_POSITIVE_RATE
    )
    training_seconds = round(time.perf_counter() - started, 1)

    champion_eval = evaluate(champion, champion_meta["threshold"], recent_holdout, old_test)
    challenger_eval = evaluate(result.model, result.threshold, recent_holdout, old_test)
    gain_share = bootstrap_gain_share(
        recent_holdout[TARGET].to_numpy(),
        champion.predict_proba(recent_holdout[FEATURES])[:, 1],
        result.model.predict_proba(recent_holdout[FEATURES])[:, 1],
        recent_holdout["player_id"].to_numpy(),
        seed,
    )
    decision = promotion_decision(champion_eval, challenger_eval, gain_share)

    version = next_version(models_dir)
    recipe = {
        "base": recipe_of(champion_meta),
        "recent": source,
        "seed": seed,
        "recent_train_share": RECENT_TRAIN_SHARE,
        "window": TRAINING_WINDOW,
    }
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "champion_version": champion_meta["version"],
        "challenger_version": version,
        "source": source,
        "training_seconds": training_seconds,
        "data": {
            "n_window": int(len(window)),
            "n_recent_train": int(len(recent) - len(recent_rest)),
            "n_recent_calibration": int(len(recent_calibration)),
            "n_recent_holdout": int(len(recent_holdout)),
            "n_old_test": int(len(old_test)),
        },
        "champion": champion_eval,
        "challenger": challenger_eval,
        "gain_share": round(gain_share, 3),
        "decision": decision,
        "meets_specification": meets_specification(challenger_eval["recent"]),
        "promoted": decision["promote"] and not dry_run,
    }

    if report["promoted"]:
        # La fiche du nouveau modèle décrit son examen final, avec le seuil recalé :
        # le "test" de v2 est l'ensemble des fiches récentes jamais vues.
        holdout_scores = result.model.predict_proba(recent_holdout[FEATURES])[:, 1]
        baseline_scores = recent_holdout["reports_received"].to_numpy(dtype=float)
        result.test_metrics = challenger_eval["recent"]
        result.fairness = fairness_report(recent_holdout, holdout_scores, result.threshold)
        result.acceptance = check_acceptance(result.test_metrics, result.fairness)
        result.baseline_test_metrics = compute_metrics(
            recent_holdout[TARGET],
            baseline_scores,
            threshold_for_max_fpr(recent_holdout[TARGET], baseline_scores, MAX_FALSE_POSITIVE_RATE),
            REVIEW_SHARE,
        )
        result.data_info["recipe"] = recipe
        save_model(
            result,
            version,
            seed,
            models_dir,
            extra={"parent_version": champion_meta["version"], "promotion": report},
        )

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"reentrainement_{version}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def summary_markdown(report: dict) -> str:
    """Résumé lisible du réentraînement (résumé GitHub Actions, description de PR)."""
    c, ch = report["champion"], report["challenger"]
    verdict = "PROMU" if report["promoted"] else "REFUSÉ"
    if report["decision"]["promote"] and not report["promoted"]:
        verdict = "PROMOUVABLE (simulation, rien d'enregistré)"
    lines = [
        f"### Réentraînement : challenger {report['challenger_version']} {verdict}",
        "",
        f"Champion actuel : {report['champion_version']} · source : `{report['source']}` · "
        f"durée : {report['training_seconds']} s · fenêtre : {report['data']['n_window']} fiches",
        "",
        "| Mesure (fiches jamais vues) | Champion | Challenger |",
        "|---|---|---|",
        f"| PR-AUC récente | {c['recent']['pr_auc']:.3f} | {ch['recent']['pr_auc']:.3f} |",
        f"| Faux positifs récents | {c['recent']['false_positive_rate']:.1%} "
        f"| {ch['recent']['false_positive_rate']:.1%} |",
        f"| Rappel récent | {c['recent']['recall']:.1%} | {ch['recent']['recall']:.1%} |",
        f"| PR-AUC ancien test | {c['old']['pr_auc']:.3f} | {ch['old']['pr_auc']:.3f} |",
        "",
        "Règles de promotion :",
        "",
        *[f"- {r}" for r in report["decision"]["reasons"]],
    ]
    if report["decision"]["promote"] and not report["meets_specification"]:
        lines += [
            "",
            "⚠️ Meilleur que le champion, mais sous les seuils du cahier des charges : "
            "le réentraînement ne suffit pas, il faut de nouvelles variables.",
        ]
    return "\n".join(lines)


def main() -> None:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description="Réentraînement du modèle Sentinel.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--scenario", help="fiches récentes de démonstration (normal, patch…)")
    action.add_argument("--current", type=Path, help="CSV de fiches récentes étiquetées")
    action.add_argument("--rollback", metavar="VERSION", help="remettre une version en production")
    parser.add_argument("--dry-run", action="store_true", help="décider sans rien enregistrer")
    parser.add_argument("--summary", type=Path, help="écrire le résumé Markdown dans ce fichier")
    args = parser.parse_args()

    if args.rollback:
        set_champion(args.rollback)
        print(f"Version en production : {args.rollback}")
        return

    if args.scenario:
        source = {"scenario": args.scenario}
    else:
        recent = pd.read_csv(args.current)
        source = {"csv": str(args.current), "fingerprint": data_fingerprint(recent)}
    report = retrain(load_source(source), source, dry_run=args.dry_run)

    text = summary_markdown(report)
    print(text)
    if args.summary:
        args.summary.write_text(text + "\n")
    # Code de sortie lisible par GitHub Actions : 0 = promu, 3 = refusé (pas une erreur).
    sys.exit(0 if report["decision"]["promote"] else 3)


if __name__ == "__main__":
    main()
