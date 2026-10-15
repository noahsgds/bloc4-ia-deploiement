"""Mesure des temps de calcul du modèle (critères 1.4 évolutivité et 2.2 temps de réponse).

Deux questions :
1. Latence : combien de temps pour scorer UNE fiche ? (usage en fin de match)
   Exigence du cahier des charges : p95 < 200 ms.
2. Débit : combien de temps pour scorer un gros lot ? (file de revue quotidienne)
   Volume quotidien attendu : environ 30 000 fiches.

Le "p95" est la latence sous laquelle se trouvent 95 % des appels : il reflète
l'expérience des cas lents, contrairement à la moyenne qui les masque.

Utilisation :
    python -m src.benchmark
"""

import time

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from src.config import FEATURES
from src.data.generate import generate_dataset
from src.train import load_champion


def single_latency_ms(model: Pipeline, X: pd.DataFrame, n_calls: int = 200) -> dict:
    """Latence de scoring d'une fiche, appel par appel (en millisecondes)."""
    durations = []
    for i in range(n_calls):
        row = X.iloc[[i % len(X)]]
        start = time.perf_counter()
        model.predict_proba(row)
        durations.append((time.perf_counter() - start) * 1000)
    return {
        "p50_ms": round(float(np.percentile(durations, 50)), 2),
        "p95_ms": round(float(np.percentile(durations, 95)), 2),
        "max_ms": round(float(np.max(durations)), 2),
    }


def batch_throughput(model: Pipeline, X: pd.DataFrame, sizes: list[int]) -> list[dict]:
    """Temps de scoring par lot, pour plusieurs tailles de lot."""
    results = []
    for size in sizes:
        batch = X.sample(size, replace=size > len(X), random_state=0)
        start = time.perf_counter()
        model.predict_proba(batch)
        seconds = time.perf_counter() - start
        results.append(
            {
                "rows": size,
                "seconds": round(seconds, 3),
                "rows_per_second": int(size / seconds),
            }
        )
    return results


def run_benchmark(model: Pipeline) -> dict:
    """Lance les deux mesures sur des données synthétiques."""
    X = generate_dataset(n_matches=20_000, seed=99)[FEATURES]
    model.predict_proba(X.head(10))  # échauffement : le premier appel est toujours plus lent
    return {
        "single": single_latency_ms(model, X),
        "batch": batch_throughput(model, X, sizes=[1_000, 10_000, 100_000]),
    }


def main() -> None:
    model, metadata = load_champion()
    results = run_benchmark(model)
    single = results["single"]
    print(f"Modèle {metadata['version']} ({metadata['model_name']})")
    print(
        f"Latence d'une fiche : p50 = {single['p50_ms']} ms, p95 = {single['p95_ms']} ms "
        f"(exigence : p95 < 200 ms)"
    )
    for line in results["batch"]:
        print(
            f"Lot de {line['rows']:>7,} fiches : {line['seconds']:>6.3f} s "
            f"({line['rows_per_second']:,} fiches/s)"
        )


if __name__ == "__main__":
    main()
