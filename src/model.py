"""Entraînement, évaluation et sauvegarde du modèle de détection de triche.

Étapes de l'entraînement (fonction ``train``) :
1. valider les données ;
2. découper en entraînement / validation / test, PAR JOUEUR ;
3. entraîner deux modèles et garder le meilleur sur la validation ;
4. choisir le seuil qui limite les faux positifs à 1 % ;
5. évaluer une seule fois sur le test : performance, équité, comparaison aux signalements.

En ligne de commande :
    python -m src.model                    # entraîne et enregistre la version v1
    python -m src.model --version v2 --data data/train.csv
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import (
    ACCEPTANCE_THRESHOLDS,
    CATEGORICAL_FEATURES,
    FEATURES,
    FPR_TOLERANCE,
    MAX_FALSE_POSITIVE_RATE,
    MAX_FPR_GAP,
    MODELS_DIR,
    NUMERIC_FEATURES,
    RANDOM_SEED,
    REVIEW_SHARE,
    TARGET,
)
from src.data import generate_dataset, validate_dataset
from src.explain import reference_by_rank, transformed_mean

AUDITED_GROUPS = ["input_device", "platform", "accessibility_mode", "age_band"]
REFERENCE_ROWS = 5_000  # échantillon gardé avec le modèle pour surveiller la dérive

# --- Les deux modèles comparés ------------------------------------------------------------


def build_candidates(seed: int) -> dict[str, Pipeline]:
    """Deux modèles, chacun = préparation des données + classifieur, dans un seul Pipeline.

    Le Pipeline applique exactement les mêmes transformations à l'entraînement et dans l'API.
    - Valeurs manquantes : remplacées par la médiane apprise à l'entraînement.
    - Catégories : une colonne 0/1 par valeur ; une valeur inconnue est ignorée (robustesse).
    - class_weight="balanced" : les tricheurs, très rares, comptent davantage.

    Régression logistique : simple et facile à expliquer (référence).
    Gradient boosting : ensemble d'arbres, capte les combinaisons de signaux.
    """

    def preparation(scale: bool) -> ColumnTransformer:
        numeric = [("median", SimpleImputer(strategy="median"))]
        if scale:  # mise à l'échelle utile pour la régression logistique, pas pour les arbres
            numeric.append(("scale", StandardScaler()))
        return ColumnTransformer(
            [
                ("num", Pipeline(numeric), NUMERIC_FEATURES),
                ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ]
        )

    return {
        "regression_logistique": Pipeline(
            [
                ("preprocessing", preparation(scale=True)),
                ("model", LogisticRegression(max_iter=1000, class_weight="balanced")),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                ("preprocessing", preparation(scale=False)),
                (
                    "model",
                    HistGradientBoostingClassifier(class_weight="balanced", random_state=seed),
                ),
            ]
        ),
    }


def split_by_player(df: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """60 % entraînement, 20 % validation, 20 % test, sans jamais séparer un joueur.

    Si les matchs d'un joueur étaient à la fois dans l'entraînement et le test, le modèle
    "reconnaîtrait" le joueur au lieu de détecter la triche : résultats trop optimistes.
    """
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=seed)
    rest_idx, test_idx = next(splitter.split(df, groups=df["player_id"]))
    rest, test = df.iloc[rest_idx], df.iloc[test_idx]
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)  # 25 % de 80 %
    train_idx, val_idx = next(splitter.split(rest, groups=rest["player_id"]))
    return rest.iloc[train_idx], rest.iloc[val_idx], test


# --- Mesures ------------------------------------------------------------------------------


def threshold_for_max_fpr(y: np.ndarray, scores: np.ndarray, max_fpr: float) -> float:
    """Seuil le plus bas qui garde la part d'honnêtes signalés à tort sous ``max_fpr``.

    On protège d'abord les innocents, puis on détecte le plus de tricheurs possible.
    """
    fpr, _, thresholds = roc_curve(y, scores)
    threshold = thresholds[np.where(fpr <= max_fpr)[0][-1]]
    if np.isinf(threshold):  # aucun seuil possible : on ne signale personne
        threshold = float(np.max(scores)) + 1e-9
    return float(threshold)


def compute_metrics(y, scores, threshold: float) -> dict:
    """Mesures du cahier des charges. Pas d'"accuracy" : avec 3 % de tricheurs, répondre
    toujours "honnête" donnerait 97 % de bonnes réponses tout en étant inutile."""
    y, scores = np.asarray(y), np.asarray(scores)
    flagged = scores >= threshold
    top = np.argsort(-scores)[: max(1, round(REVIEW_SHARE * len(scores)))]
    return {
        "roc_auc": round(float(roc_auc_score(y, scores)), 4),
        "pr_auc": round(float(average_precision_score(y, scores)), 4),
        "precision_top": round(float(y[top].mean()), 4),  # vrais tricheurs dans le 1 % examiné
        "recall": round(float(flagged[y == 1].mean()), 4),  # tricheurs détectés
        "false_positive_rate": round(float(flagged[y == 0].mean()), 4),  # honnêtes signalés
        "n_samples": int(len(y)),
    }


def fairness_report(df: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict:
    """Taux de faux positifs par groupe de joueurs, et écart entre groupes.

    Exemple : les joueurs à la manette sont-ils plus souvent soupçonnés à tort ?
    Les groupes de moins de 100 joueurs honnêtes sont ignorés (taux trop incertain).
    Résultats uniquement agrégés, jamais par joueur (protection des variables d'audit).
    """
    df = df.assign(_flagged=np.asarray(scores) >= threshold)
    honest = df[df[TARGET] == 0]
    report = {}
    for group in AUDITED_GROUPS:
        counts = honest.groupby(group)["_flagged"].agg(["mean", "size"])
        rates = {
            str(k): round(float(r["mean"]), 4) for k, r in counts.iterrows() if r["size"] >= 100
        }
        gap = round(max(rates.values()) - min(rates.values()), 4) if len(rates) >= 2 else 0.0
        report[group] = {"fpr_by_group": rates, "gap": gap, "passed": gap < MAX_FPR_GAP}
    return report


def check_acceptance(metrics: dict, fairness: dict) -> dict:
    """Le modèle respecte-t-il le cahier des charges ? Il doit être performant ET équitable."""
    checks = {name: metrics[name] >= minimum for name, minimum in ACCEPTANCE_THRESHOLDS.items()}
    checks["false_positive_rate"] = metrics["false_positive_rate"] <= FPR_TOLERANCE
    checks["fairness"] = all(group["passed"] for group in fairness.values())
    return {"passed": all(checks.values()), "details": checks}


# --- Entraînement -------------------------------------------------------------------------


def train(df: pd.DataFrame, seed: int = RANDOM_SEED) -> tuple[Pipeline, dict]:
    """Entraîne, choisit et évalue le modèle.

    Returns:
        (modèle retenu, fiche d'informations : seuil, mesures, équité, données utilisées)
    """
    validate_dataset(df)
    train_df, val_df, test_df = split_by_player(df, seed)

    # 1. Chaque candidat apprend sur l'entraînement et reçoit son seuil sur la validation.
    candidates = {}
    for name, pipeline in build_candidates(seed).items():
        pipeline.fit(train_df[FEATURES], train_df[TARGET])
        scores = pipeline.predict_proba(val_df[FEATURES])[:, 1]
        threshold = threshold_for_max_fpr(val_df[TARGET], scores, MAX_FALSE_POSITIVE_RATE)
        candidates[name] = (pipeline, threshold, compute_metrics(val_df[TARGET], scores, threshold))

    # 2. On garde celui qui a la meilleure PR-AUC sur la validation.
    best = max(candidates, key=lambda name: candidates[name][2]["pr_auc"])
    model, threshold, _ = candidates[best]

    # 3. Évaluation finale sur le test, jamais vu jusqu'ici.
    test_scores = model.predict_proba(test_df[FEATURES])[:, 1]
    test_metrics = compute_metrics(test_df[TARGET], test_scores, threshold)
    fairness = fairness_report(test_df, test_scores, threshold)

    # 4. Comparaison à la règle actuelle des modérateurs : trier par nombre de signalements.
    reports = test_df["reports_received"].to_numpy(dtype=float)
    baseline = compute_metrics(
        test_df[TARGET],
        reports,
        threshold_for_max_fpr(test_df[TARGET], reports, MAX_FALSE_POSITIVE_RATE),
    )

    info = {
        "model_name": best,
        "threshold": threshold,
        "validation_pr_auc": {name: c[2]["pr_auc"] for name, c in candidates.items()},
        "test_metrics": test_metrics,
        "baseline_test_metrics": baseline,
        "fairness": fairness,
        "acceptance": check_acceptance(test_metrics, fairness),
        "explain_info": {
            "reference_by_rank": reference_by_rank(train_df),
            "background_mean": transformed_mean(model, train_df),
        },
        "data": {
            "fingerprint": data_fingerprint(df),
            "n_rows": int(len(df)),
            "period": [str(df["match_date"].min()), str(df["match_date"].max())],
        },
        "_reference_sample": train_df.sample(min(REFERENCE_ROWS, len(train_df)), random_state=seed)[
            FEATURES + [TARGET]
        ],
    }
    return model, info


def data_fingerprint(df: pd.DataFrame) -> str:
    """Empreinte des données : deux jeux identiques ont la même (traçabilité)."""
    row_hashes = pd.util.hash_pandas_object(df, index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:16]


def git_commit() -> str:
    """Version du code utilisée pour l'entraînement."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        )
        return out.stdout.strip() or "inconnu"
    except OSError:
        return "inconnu"


# --- Sauvegarde et chargement -------------------------------------------------------------


def save_model(model: Pipeline, info: dict, version: str, seed: int, models_dir=MODELS_DIR) -> None:
    """Enregistre le modèle, sa fiche JSON et son échantillon de référence, puis le met en
    production (champion.json). L'échantillon ne contient ni identifiant ni variable d'audit."""
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    info = dict(info)
    info.pop("_reference_sample").to_csv(models_dir / f"reference_{version}.csv", index=False)
    joblib.dump(model, models_dir / f"cheat_model_{version}.joblib")
    metadata = {
        "version": version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed,
        "git_commit": git_commit(),
        "sklearn_version": sklearn.__version__,
        "features": FEATURES,
        **info,
    }
    text = json.dumps(metadata, indent=2, ensure_ascii=False)
    (models_dir / f"cheat_model_{version}.json").write_text(text)
    set_champion(version, models_dir)


def set_champion(version: str, models_dir=MODELS_DIR) -> None:
    """Désigne la version en production. Sert aussi à revenir en arrière."""
    models_dir = Path(models_dir)
    if not (models_dir / f"cheat_model_{version}.joblib").exists():
        raise FileNotFoundError(f"Version inconnue : {version}")
    (models_dir / "champion.json").write_text(json.dumps({"version": version}) + "\n")


def load_champion(models_dir=MODELS_DIR) -> tuple[Pipeline, dict]:
    """Charge le modèle en production et sa fiche d'informations."""
    models_dir = Path(models_dir)
    champion = models_dir / "champion.json"
    if not champion.exists():
        raise FileNotFoundError(f"Aucun modèle dans {models_dir} : lancer python -m src.model")
    version = json.loads(champion.read_text())["version"]
    model = joblib.load(models_dir / f"cheat_model_{version}.joblib")
    metadata = json.loads((models_dir / f"cheat_model_{version}.json").read_text())
    return model, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Entraîne le modèle de détection de triche.")
    parser.add_argument("--data", type=Path, help="CSV d'entraînement (sinon : données générées)")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()

    df = pd.read_csv(args.data) if args.data else generate_dataset(seed=args.seed)
    model, info = train(df, args.seed)
    save_model(model, info, args.version, args.seed)

    print(f"Modèle retenu : {info['model_name']} (version {args.version})")
    print("Test - modèle       :", info["test_metrics"])
    print("Test - signalements :", info["baseline_test_metrics"])
    print("Cahier des charges  :", "OK" if info["acceptance"]["passed"] else "NON ATTEINT")


if __name__ == "__main__":
    main()
