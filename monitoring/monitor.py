"""Surveillance du modèle en production (critères 2.3 et 3.4 du bloc 4).

Deux questions, deux contrôles :
1. Les données ont-elles changé ? (dérive des données)
   Evidently compare les fiches récentes à l'échantillon de référence gardé avec le
   modèle. Distance de Wasserstein pour les nombres, Jensen-Shannon pour les catégories :
   0 = identiques ; au-delà de 0,1, on considère que la variable a dérivé.
2. Le modèle se trompe-t-il davantage ? (dérive de performance)
   Sur les fiches dont la vérité est connue (après enquête), on recalcule la PR-AUC et
   la part d'honnêtes signalés, et on compare au test d'origine.

Résultat : statut "ok" ou "alerte" avec les raisons, rapport HTML Evidently et résumé JSON.

Utilisation :
    python -m monitoring.monitor --scenario normal | patch | humanisee
    python -m monitoring.monitor --current fiches_recentes.csv
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from src.config import (
    CATEGORICAL_FEATURES,
    DRIFT_COLUMN_THRESHOLD,
    DRIFT_SHARE_ALERT,
    FEATURES,
    MAX_PR_AUC_DROP,
    MODELS_DIR,
    MONITORING_MAX_FPR,
    NUMERIC_FEATURES,
    REPORTS_DIR,
    TARGET,
)
from src.data import SCENARIOS, scenario_data, validate_dataset
from src.model import compute_metrics, load_champion


def data_drift(reference: pd.DataFrame, current: pd.DataFrame, html_path: Path) -> dict:
    """Distance entre référence et fiches récentes pour chaque variable (Evidently)."""
    from evidently import DataDefinition, Dataset, Report
    from evidently.metrics import ValueDrift

    definition = DataDefinition(
        numerical_columns=NUMERIC_FEATURES, categorical_columns=CATEGORICAL_FEATURES
    )
    metrics = [ValueDrift(column=c, method="wasserstein") for c in NUMERIC_FEATURES] + [
        ValueDrift(column=c, method="jensenshannon") for c in CATEGORICAL_FEATURES
    ]
    snapshot = Report(metrics).run(
        Dataset.from_pandas(current[FEATURES], data_definition=definition),
        Dataset.from_pandas(reference[FEATURES], data_definition=definition),
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(html_path))
    return {m["config"]["column"]: round(float(m["value"]), 4) for m in snapshot.dict()["metrics"]}


def decide(distances: dict, current: dict | None, reference: dict) -> dict:
    """Applique les seuils d'alerte. Logique simple, testée sans Evidently."""
    drifted = sorted(c for c, d in distances.items() if d >= DRIFT_COLUMN_THRESHOLD)
    reasons = []
    if len(drifted) / len(distances) >= DRIFT_SHARE_ALERT:
        reasons.append(f"Les données ont changé : {', '.join(drifted)}")
    if current is not None:
        drop = reference["pr_auc"] - current["pr_auc"]
        if drop > MAX_PR_AUC_DROP:
            reasons.append(
                f"PR-AUC en baisse : {reference['pr_auc']:.2f} -> {current['pr_auc']:.2f}"
            )
        if current["false_positive_rate"] > MONITORING_MAX_FPR:
            reasons.append(f"{current['false_positive_rate']:.1%} d'honnêtes signalés à tort")
    return {"status": "alerte" if reasons else "ok", "reasons": reasons, "drifted": drifted}


def monitor(
    current: pd.DataFrame, label: str, models_dir=MODELS_DIR, reports_dir=REPORTS_DIR
) -> dict:
    """Lance les deux contrôles et écrit le rapport HTML et le résumé JSON."""
    validate_dataset(current)
    model, meta = load_champion(models_dir)
    reference = pd.read_csv(Path(models_dir) / f"reference_{meta['version']}.csv")
    distances = data_drift(reference, current, Path(reports_dir) / f"derive_{label}.html")

    performance = None
    if current[TARGET].notna().all():  # vérité connue : on peut mesurer la performance
        scores = model.predict_proba(current[FEATURES])[:, 1]
        performance = compute_metrics(current[TARGET], scores, meta["threshold"])

    summary = {
        "label": label,
        "model_version": meta["version"],
        "distances": distances,
        "performance": performance,
        **decide(distances, performance, meta["test_metrics"]),
    }
    path = Path(reports_dir) / "dernier_resume.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Surveillance du modèle Sentinel.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", choices=list(SCENARIOS))
    source.add_argument("--current", type=Path, help="CSV de fiches récentes")
    args = parser.parse_args()
    if args.scenario:
        current, label = scenario_data(args.scenario), args.scenario
    else:
        current, label = pd.read_csv(args.current), args.current.stem
    summary = monitor(current, label)
    print(f"Statut : {summary['status']}")
    for reason in summary["reasons"]:
        print(f"- {reason}")


if __name__ == "__main__":
    main()
