"""Surveillance du modèle (étape 9) — critères 3.4 (dérive) et 2.3 (alertes) du bloc 4.

Deux questions, deux contrôles :

1. Les données d'entrée ont-elles changé ? (dérive des données / "data drift")
   On compare les statistiques des matchs récents à celles du jeu d'entraînement avec
   Evidently. Pas besoin de savoir qui triche : ce contrôle peut tourner chaque jour.

2. Le modèle se trompe-t-il davantage ? (dérive de performance / "concept drift")
   On recalcule PR-AUC et taux de faux positifs sur les fiches dont la vérité est connue
   (décision du modérateur après enquête). C'est le seul moyen de voir une triche qui a
   changé de forme sans que les statistiques globales bougent (triche "humanisée").

Le script produit un rapport HTML Evidently et un résumé JSON, avec un statut
"ok" ou "alerte" et les raisons de l'alerte.

Utilisation :
    python -m monitoring.drift_report --scenario normal
    python -m monitoring.drift_report --scenario patch       # mise à jour du jeu
    python -m monitoring.drift_report --scenario humanisee   # triche plus discrète
    python -m monitoring.drift_report --current data/matchs_recents.csv
    Option --fail-on-alert : code de sortie 1 en cas d'alerte (utile dans GitHub Actions).
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import (
    CATEGORICAL_FEATURES,
    DRIFT_COLUMN_THRESHOLD,
    DRIFT_SHARE_ALERT,
    MAX_PR_AUC_DROP,
    MODELS_DIR,
    MONITORING_MAX_FPR,
    NUMERIC_FEATURES,
    REPORTS_DIR,
    REVIEW_SHARE,
    TARGET,
)
from src.data.generate import generate_dataset
from src.data.validate import validate_dataset
from src.evaluate import compute_metrics
from src.train import data_fingerprint, load_champion

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Les trois situations de la démo. Graine et dates différentes de l'entraînement :
# ce sont de NOUVEAUX joueurs, sur une période postérieure (octobre 2026).
SCENARIOS = {
    "normal": {"cheat_intensity": 1.0, "game_patch": False},
    "patch": {"cheat_intensity": 1.0, "game_patch": True},
    "humanisee": {"cheat_intensity": 0.4, "game_patch": False},
}
SCENARIO_ROWS = 30_000  # environ une journée d'activité
SCENARIO_SEED = 2026
SCENARIO_START = "2026-10-01"


# --- Données ----------------------------------------------------------------------------


def load_reference(metadata: dict) -> pd.DataFrame:
    """Régénère le jeu d'entraînement du modèle et vérifie que c'est bien le même.

    Les données ne sont pas versionnées dans Git (elles sont régénérables) : on les
    recrée à partir de la graine et du nombre de lignes enregistrés dans les métadonnées,
    puis on compare l'empreinte. Si elle diffère, la comparaison n'aurait aucun sens.
    """
    data_info = metadata["data"]
    reference = generate_dataset(n_matches=data_info["n_rows"], seed=metadata["seed"])
    fingerprint = data_fingerprint(reference)
    if fingerprint != data_info["fingerprint"]:
        raise RuntimeError(
            f"Données de référence différentes de celles de l'entraînement "
            f"(empreinte {fingerprint} au lieu de {data_info['fingerprint']})."
        )
    return reference


def scenario_data(name: str) -> pd.DataFrame:
    """Crée les matchs "récents" d'un scénario de démonstration."""
    if name not in SCENARIOS:
        raise ValueError(f"Scénario inconnu : {name}. Choix : {', '.join(SCENARIOS)}")
    return generate_dataset(
        n_matches=SCENARIO_ROWS,
        seed=SCENARIO_SEED,
        start_date=SCENARIO_START,
        **SCENARIOS[name],
    )


# --- Règles de décision (logique pure, testée sans Evidently) ---------------------------


def data_drift_status(column_scores: dict[str, float]) -> dict:
    """Décide s'il y a dérive des données à partir des distances calculées par Evidently.

    Args:
        column_scores: pour chaque variable, la distance entre référence et données
            récentes (0 = identiques ; plus c'est grand, plus elles diffèrent).
    """
    drifted = sorted(c for c, s in column_scores.items() if s >= DRIFT_COLUMN_THRESHOLD)
    share = len(drifted) / len(column_scores) if column_scores else 0.0
    return {
        "scores": {c: round(float(s), 4) for c, s in column_scores.items()},
        "drifted_columns": drifted,
        "drifted_share": round(share, 4),
        "alert": share >= DRIFT_SHARE_ALERT,
    }


def performance_status(current: dict, reference: dict) -> dict:
    """Compare les performances récentes à celles mesurées sur le jeu de test."""
    pr_auc_drop = reference["pr_auc"] - current["pr_auc"]
    reasons = []
    if pr_auc_drop > MAX_PR_AUC_DROP:
        reasons.append(
            f"PR-AUC en baisse de {pr_auc_drop:.2f} "
            f"({reference['pr_auc']:.2f} -> {current['pr_auc']:.2f})"
        )
    if current["false_positive_rate"] > MONITORING_MAX_FPR:
        reasons.append(
            f"{current['false_positive_rate']:.1%} de joueurs honnêtes signalés à tort "
            f"(maximum {MONITORING_MAX_FPR:.0%})"
        )
    return {
        "current": current,
        "reference": {k: reference[k] for k in ("pr_auc", "false_positive_rate", "recall")},
        "pr_auc_drop": round(pr_auc_drop, 4),
        "reasons": reasons,
        "alert": bool(reasons),
    }


def overall_status(data_drift: dict, performance: dict | None) -> dict:
    """Assemble les deux contrôles en un statut unique et des raisons lisibles."""
    reasons = []
    if data_drift["alert"]:
        cols = ", ".join(data_drift["drifted_columns"])
        reasons.append(
            f"Dérive des données sur {len(data_drift['drifted_columns'])} variables : {cols}"
        )
    if performance is not None:
        reasons.extend(performance["reasons"])
    return {"status": "alerte" if reasons else "ok", "reasons": reasons}


# --- Calculs ----------------------------------------------------------------------------


def run_evidently(reference: pd.DataFrame, current: pd.DataFrame, html_path: Path) -> dict:
    """Calcule la dérive de chaque variable avec Evidently et enregistre le rapport HTML.

    Méthodes : distance de Wasserstein normalisée pour les nombres, Jensen-Shannon pour
    les catégories. On a écarté le test de Kolmogorov-Smirnov (choix par défaut sur
    les petits jeux) : les lignes d'un même joueur ne sont pas indépendantes et, avec
    des dizaines de milliers de lignes, ce test signale une "dérive" pour des écarts
    minuscules (fausses alertes constatées en étape 9, voir journal de bord).

    Returns:
        Un dictionnaire {variable: distance}. La colonne "score" (score du modèle) est
        incluse : c'est la dérive des prédictions.
    """
    # Import ici : Evidently n'est nécessaire que pour ce script, pas pour l'API.
    from evidently import DataDefinition, Dataset, Report
    from evidently.metrics import DriftedColumnsCount, ValueDrift

    numeric = NUMERIC_FEATURES + ["score"]
    definition = DataDefinition(numerical_columns=numeric, categorical_columns=CATEGORICAL_FEATURES)
    method = {c: "wasserstein" for c in numeric} | {
        c: "jensenshannon" for c in CATEGORICAL_FEATURES
    }

    metrics = [
        DriftedColumnsCount(
            columns=FEATURES,
            drift_share=DRIFT_SHARE_ALERT,
            num_method="wasserstein",
            cat_method="jensenshannon",
        )
    ]
    metrics += [
        ValueDrift(column=c, method=method[c], threshold=DRIFT_COLUMN_THRESHOLD) for c in method
    ]

    columns = FEATURES + ["score"]
    snapshot = Report(metrics).run(
        Dataset.from_pandas(current[columns], data_definition=definition),
        Dataset.from_pandas(reference[columns], data_definition=definition),
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(html_path))

    scores = {}
    for metric in snapshot.dict()["metrics"]:
        column = metric.get("config", {}).get("column")
        if column is not None:
            scores[column] = float(metric["value"])
    return scores


def score(model, df: pd.DataFrame) -> np.ndarray:
    """Score de suspicion du modèle pour chaque ligne."""
    return model.predict_proba(df[FEATURES])[:, 1]


def build_report(
    current: pd.DataFrame,
    label: str,
    models_dir: Path = MODELS_DIR,
    reports_dir: Path = REPORTS_DIR,
) -> dict:
    """Lance les deux contrôles et écrit le rapport HTML et le résumé JSON."""
    validate_dataset(current)  # on ne surveille pas des données invalides
    model, metadata = load_champion(models_dir)
    reference = load_reference(metadata)
    reference = reference.assign(score=score(model, reference))
    current = current.assign(score=score(model, current))

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    html_path = reports_dir / f"derive_{label}_{stamp}.html"
    column_scores = run_evidently(reference, current, html_path)

    prediction_drift = column_scores.pop("score", None)
    data_drift = data_drift_status({c: column_scores[c] for c in FEATURES})

    performance = None
    if TARGET in current.columns and current[TARGET].notna().any():
        labelled = current[current[TARGET].notna()]
        metrics = compute_metrics(
            labelled[TARGET].astype(int).to_numpy(),
            labelled["score"].to_numpy(),
            metadata["threshold"],
            REVIEW_SHARE,
        )
        performance = performance_status(metrics, metadata["test_metrics"])

    summary = {
        "label": label,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_version": metadata["version"],
        "n_rows": int(len(current)),
        "data_drift": data_drift,
        "prediction_drift": {
            "score_distance": None if prediction_drift is None else round(prediction_drift, 4),
            "flagged_share_reference": round(
                float((reference["score"] >= metadata["threshold"]).mean()), 4
            ),
            "flagged_share_current": round(
                float((current["score"] >= metadata["threshold"]).mean()), 4
            ),
        },
        "performance": performance,
        **overall_status(data_drift, performance),
        "html_report": html_path.name,
    }
    json_path = reports_dir / f"derive_{label}_{stamp}.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (reports_dir / "dernier_resume.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    return summary


def main() -> None:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description="Surveillance de la dérive du modèle Sentinel.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", choices=list(SCENARIOS), help="données de démonstration")
    source.add_argument("--current", type=Path, help="fichier CSV des matchs récents")
    parser.add_argument("--fail-on-alert", action="store_true", help="code 1 si alerte")
    args = parser.parse_args()

    if args.scenario:
        current, label = scenario_data(args.scenario), args.scenario
    else:
        current, label = pd.read_csv(args.current), args.current.stem

    summary = build_report(current, label)
    print(
        json.dumps(
            {k: summary[k] for k in ("label", "status", "reasons")}, indent=2, ensure_ascii=False
        )
    )
    print(f"Rapport : {REPORTS_DIR / summary['html_report']}")
    if args.fail_on_alert and summary["status"] == "alerte":
        sys.exit(1)


if __name__ == "__main__":
    main()
