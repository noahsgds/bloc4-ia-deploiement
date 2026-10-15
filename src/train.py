"""Entraînement, sélection et sauvegarde du modèle de détection de triche.

Étapes :
1. Charger (ou générer) les données, puis valider le contrat.
2. Découper en entraînement / validation / test, PAR JOUEUR (voir split_by_player).
3. Entraîner deux modèles candidats et garder le meilleur sur la validation.
4. Choisir le seuil de décision qui limite les faux positifs à 1 %.
5. Évaluer une seule fois sur le jeu de test, et comparer à la règle actuelle (signalements).
6. Sauvegarder le modèle et ses métadonnées (métriques, données, graine, version du code).

Utilisation :
    python -m src.train                       # génère 50 000 lignes et entraîne
    python -m src.train --data data/train.csv --version v2
"""

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

from src.config import (
    ACCEPTANCE_THRESHOLDS,
    FEATURES,
    MAX_FALSE_POSITIVE_RATE,
    MODELS_DIR,
    RANDOM_SEED,
    REVIEW_SHARE,
    TARGET,
    TEST_SHARE,
    VALIDATION_SHARE,
)
from src.data.generate import generate_dataset
from src.data.validate import validate_dataset
from src.evaluate import compute_metrics, threshold_for_max_fpr
from src.explain import reference_by_rank, transformed_mean
from src.fairness import fairness_passed, fairness_report
from src.features import build_preprocessor


def build_candidates(seed: int) -> dict[str, Pipeline]:
    """Les deux modèles comparés. Chacun = preprocessing + classifieur dans un seul Pipeline.

    - Régression logistique : simple, rapide, facile à expliquer (baseline de référence).
    - HistGradientBoosting : ensemble d'arbres de décision, capte les interactions entre
      variables (ex. précision élevée ET temps de réaction très bas).

    class_weight="balanced" donne plus de poids aux tricheurs, très minoritaires, pour
    que le modèle ne se contente pas de prédire "honnête" partout.
    """
    return {
        "regression_logistique": Pipeline(
            [
                ("preprocessing", build_preprocessor(scale_numeric=True)),
                ("model", LogisticRegression(max_iter=1000, class_weight="balanced")),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                ("preprocessing", build_preprocessor(scale_numeric=False)),
                (
                    "model",
                    HistGradientBoostingClassifier(class_weight="balanced", random_state=seed),
                ),
            ]
        ),
    }


def split_by_player(df: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Découpe les données en entraînement / validation / test, sans mélanger les joueurs.

    Pourquoi par joueur ? Un même joueur joue plusieurs matchs. Si certains de ses matchs
    étaient dans l'entraînement et d'autres dans le test, le modèle "reconnaîtrait" le
    joueur (même ancienneté de compte, même rang...) au lieu d'apprendre à détecter la
    triche : les scores de test seraient trop optimistes. C'est une fuite de données.
    """
    groups = df["player_id"]
    test_splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SHARE, random_state=seed)
    rest_idx, test_idx = next(test_splitter.split(df, groups=groups))
    rest, test = df.iloc[rest_idx], df.iloc[test_idx]

    # La validation est prise dans ce qui reste (20 % du total = 25 % du reste).
    val_size = VALIDATION_SHARE / (1 - TEST_SHARE)
    val_splitter = GroupShuffleSplit(n_splits=1, test_size=val_size, random_state=seed)
    train_idx, val_idx = next(val_splitter.split(rest, groups=rest["player_id"]))
    return rest.iloc[train_idx], rest.iloc[val_idx], test


def data_fingerprint(df: pd.DataFrame) -> str:
    """Empreinte unique des données d'entraînement (traçabilité, critère 3.5).

    Deux jeux de données identiques ont la même empreinte : on sait toujours sur quelles
    données exactes un modèle a été entraîné.
    """
    row_hashes = pd.util.hash_pandas_object(df, index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:16]


def current_git_commit() -> str:
    """Identifiant du commit Git du code utilisé pour l'entraînement ('inconnu' si indisponible)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "inconnu"


@dataclass
class TrainingResult:
    """Tout ce que produit un entraînement : le modèle retenu et ses justificatifs."""

    model: Pipeline
    model_name: str
    threshold: float
    validation_metrics: dict = field(default_factory=dict)  # par modèle candidat
    test_metrics: dict = field(default_factory=dict)  # modèle retenu, sur le test
    baseline_test_metrics: dict = field(default_factory=dict)  # règle des signalements
    acceptance: dict = field(default_factory=dict)  # seuils du cahier des charges
    fairness: dict = field(default_factory=dict)  # audit d'équité sur le test
    explain_info: dict = field(default_factory=dict)  # références pour les explications
    data_info: dict = field(default_factory=dict)


def check_acceptance(metrics: dict, fairness: dict) -> dict:
    """Compare les résultats de test aux seuils d'acceptation du cahier des charges.

    Un modèle n'est acceptable que s'il est à la fois performant ET équitable.
    """
    checks = {name: metrics[name] >= minimum for name, minimum in ACCEPTANCE_THRESHOLDS.items()}
    checks["false_positive_rate"] = metrics["false_positive_rate"] <= MAX_FALSE_POSITIVE_RATE * 1.5
    checks["fairness"] = fairness_passed(fairness)
    return {"passed": all(checks.values()), "details": checks}


def train_and_select(df: pd.DataFrame, seed: int = RANDOM_SEED) -> TrainingResult:
    """Entraîne les candidats, choisit le meilleur, fixe le seuil et évalue sur le test."""
    validate_dataset(df)
    train, val, test = split_by_player(df, seed)

    validation_metrics, fitted = {}, {}
    for name, pipeline in build_candidates(seed).items():
        pipeline.fit(train[FEATURES], train[TARGET])
        val_scores = pipeline.predict_proba(val[FEATURES])[:, 1]
        threshold = threshold_for_max_fpr(val[TARGET], val_scores, MAX_FALSE_POSITIVE_RATE)
        validation_metrics[name] = compute_metrics(val[TARGET], val_scores, threshold, REVIEW_SHARE)
        fitted[name] = (pipeline, threshold)

    # Le modèle retenu est celui qui a la meilleure PR-AUC sur la validation.
    best_name = max(validation_metrics, key=lambda n: validation_metrics[n]["pr_auc"])
    best_model, best_threshold = fitted[best_name]

    # Évaluation finale sur le test, jamais vu pendant l'entraînement ni le choix du modèle.
    test_scores = best_model.predict_proba(test[FEATURES])[:, 1]
    test_metrics = compute_metrics(test[TARGET], test_scores, best_threshold, REVIEW_SHARE)
    fairness = fairness_report(test, test_scores, best_threshold)

    # Règle actuelle des modérateurs : trier par nombre de signalements.
    baseline_scores = test["reports_received"].to_numpy(dtype=float)
    baseline_threshold = threshold_for_max_fpr(
        test[TARGET], baseline_scores, MAX_FALSE_POSITIVE_RATE
    )
    baseline_metrics = compute_metrics(
        test[TARGET], baseline_scores, baseline_threshold, REVIEW_SHARE
    )

    return TrainingResult(
        model=best_model,
        model_name=best_name,
        threshold=best_threshold,
        validation_metrics=validation_metrics,
        test_metrics=test_metrics,
        baseline_test_metrics=baseline_metrics,
        acceptance=check_acceptance(test_metrics, fairness),
        fairness=fairness,
        explain_info={
            "reference_by_rank": reference_by_rank(train),
            "background_mean": transformed_mean(best_model, train),
        },
        data_info={
            "fingerprint": data_fingerprint(df),
            "n_rows": int(len(df)),
            "n_train": int(len(train)),
            "n_validation": int(len(val)),
            "n_test": int(len(test)),
            "period": [str(df["match_date"].min()), str(df["match_date"].max())],
        },
    )


def save_model(
    result: TrainingResult, version: str, seed: int, models_dir: Path = MODELS_DIR
) -> Path:
    """Sauvegarde le modèle (.joblib) et sa fiche de métadonnées (.json).

    Le fichier champion.json indique quelle version est en production.
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    model_path = models_dir / f"cheat_model_{version}.joblib"
    joblib.dump(result.model, model_path)

    metadata = {
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_name": result.model_name,
        "threshold": result.threshold,
        "features": FEATURES,
        "seed": seed,
        "git_commit": current_git_commit(),
        "sklearn_version": sklearn.__version__,
        "data": result.data_info,
        "validation_metrics": result.validation_metrics,
        "test_metrics": result.test_metrics,
        "baseline_test_metrics": result.baseline_test_metrics,
        "acceptance": result.acceptance,
        "fairness": result.fairness,
        "explain_info": result.explain_info,
    }
    metadata_path = models_dir / f"cheat_model_{version}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    champion_path = models_dir / "champion.json"
    champion_path.write_text(json.dumps({"version": version}, indent=2))
    return model_path


def load_champion(models_dir: Path = MODELS_DIR) -> tuple[Pipeline, dict]:
    """Charge le modèle en production et ses métadonnées.

    Raises:
        FileNotFoundError: si aucun modèle n'a encore été entraîné.
    """
    champion_path = models_dir / "champion.json"
    if not champion_path.exists():
        raise FileNotFoundError(
            f"Aucun modèle champion dans {models_dir}. Lancez d'abord : python -m src.train"
        )
    version = json.loads(champion_path.read_text())["version"]
    model = joblib.load(models_dir / f"cheat_model_{version}.joblib")
    metadata = json.loads((models_dir / f"cheat_model_{version}.json").read_text())
    return model, metadata


def main() -> None:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description="Entraîne le modèle de détection de triche.")
    parser.add_argument("--data", type=Path, help="CSV d'entraînement (sinon : données générées)")
    parser.add_argument("--n-matches", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    if args.data:
        df = pd.read_csv(args.data)
    else:
        df = generate_dataset(n_matches=args.n_matches, seed=args.seed)

    np.random.seed(args.seed)  # par sécurité, pour toute bibliothèque utilisant l'aléa global
    result = train_and_select(df, seed=args.seed)
    model_path = save_model(result, args.version, args.seed)

    print(f"Modèle retenu : {result.model_name} -> {model_path}")
    print(f"Seuil de décision : {result.threshold:.3f}")
    print("Validation (PR-AUC) :", {k: v["pr_auc"] for k, v in result.validation_metrics.items()})
    print("Test - modèle      :", result.test_metrics)
    print("Test - signalements:", result.baseline_test_metrics)
    status = "OK" if result.acceptance["passed"] else "NON ATTEINTS"
    print(f"Seuils d'acceptation : {status} {result.acceptance['details']}")


if __name__ == "__main__":
    main()
