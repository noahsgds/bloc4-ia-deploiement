"""Réentraînement du modèle sur des fiches récentes (critères 3.1, 3.2, 3.3 et 3.5).

Quand la surveillance lève une alerte, on réentraîne sur les fiches récentes dont la
vérité est connue (décisions des modérateurs) :
1. les fiches récentes sont coupées par joueur : 70 % pour apprendre, 30 % pour l'examen ;
2. un nouveau modèle ("challenger") est entraîné avec exactement la même méthode que v1 ;
3. l'ancien ("champion") et le nouveau passent le MÊME examen, sur des fiches jamais vues ;
4. le nouveau ne remplace l'ancien que s'il est meilleur, n'accuse pas plus de 1,5 %
   d'innocents et reste équitable entre les groupes de joueurs.

Pourquoi seulement les fiches récentes ? Après une mise à jour du jeu, les anciennes
statistiques décrivent un jeu qui n'existe plus.

Utilisation :
    python -m monitoring.retrain --scenario patch
    python -m monitoring.retrain --current fiches_etiquetees.csv
    python -m monitoring.retrain --rollback v1        # revenir à une version précédente
"""

import argparse
from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from src.config import FEATURES, FPR_TOLERANCE, MODELS_DIR, RANDOM_SEED, TARGET
from src.data import SCENARIOS, scenario_data, validate_dataset
from src.model import (
    compute_metrics,
    fairness_report,
    load_champion,
    save_model,
    set_champion,
    train,
)


def evaluate(model, threshold: float, exam: pd.DataFrame) -> dict:
    """Mesures d'un modèle sur l'examen, avec son propre seuil."""
    scores = model.predict_proba(exam[FEATURES])[:, 1]
    fairness = fairness_report(exam, scores, threshold)
    return {
        **compute_metrics(exam[TARGET], scores, threshold),
        "fair": all(group["passed"] for group in fairness.values()),
    }


def decide(champion: dict, challenger: dict) -> dict:
    """Les trois règles de promotion, toutes obligatoires."""
    rules = {
        "meilleur que le modèle actuel (PR-AUC)": challenger["pr_auc"] > champion["pr_auc"],
        "au plus 1,5 % d'honnêtes signalés à tort": challenger["false_positive_rate"]
        <= FPR_TOLERANCE,
        "équitable entre les groupes de joueurs": challenger["fair"],
    }
    return {"promote": all(rules.values()), "rules": rules}


def retrain(recent: pd.DataFrame, models_dir=MODELS_DIR, seed: int = RANDOM_SEED) -> dict:
    """Entraîne un challenger sur les fiches récentes et le promeut s'il passe les règles."""
    validate_dataset(recent)  # un format modifié arrête tout, avec un message clair
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=seed)
    learn_idx, exam_idx = next(splitter.split(recent, groups=recent["player_id"]))
    learn, exam = recent.iloc[learn_idx], recent.iloc[exam_idx]

    champion, champion_meta = load_champion(models_dir)
    challenger, info = train(learn, seed)
    report = {
        "champion_version": champion_meta["version"],
        "champion": evaluate(champion, champion_meta["threshold"], exam),
        "challenger": evaluate(challenger, info["threshold"], exam),
    }
    report.update(decide(report["champion"], report["challenger"]))

    if report["promote"]:
        version = f"v{int(champion_meta['version'][1:]) + 1}"
        info["parent_version"] = champion_meta["version"]
        save_model(challenger, info, version, seed, models_dir)
        report["new_version"] = version
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Réentraînement du modèle Sentinel.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--scenario", choices=list(SCENARIOS))
    action.add_argument("--current", type=Path, help="CSV de fiches récentes étiquetées")
    action.add_argument("--rollback", metavar="VERSION", help="ex. v1")
    args = parser.parse_args()

    if args.rollback:
        set_champion(args.rollback)
        print(f"Version en production : {args.rollback}")
        return
    recent = scenario_data(args.scenario) if args.scenario else pd.read_csv(args.current)
    report = retrain(recent)
    for name in ("champion", "challenger"):
        m = report[name]
        print(f"{name:10} PR-AUC {m['pr_auc']:.3f} | faux positifs {m['false_positive_rate']:.1%}")
    for rule, ok in report["rules"].items():
        print(f"{'OK ' if ok else 'NON'} {rule}")
    print(f"Nouveau modèle en production : {report['new_version']}" if report["promote"]
          else "Modèle actuel conservé.")  # fmt: skip


if __name__ == "__main__":
    main()
