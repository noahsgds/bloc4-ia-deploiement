"""Tests de temps de réponse et de montée en charge (critères 1.4 et 2.2 ; CA-05).

Seuils volontairement larges : une machine d'intégration continue est plus lente qu'un
poste de développement, et un test qui échoue au hasard serait pire qu'inutile.

Lancer : pytest tests/test_performance.py -v
"""

import pytest

from src.benchmark import run_benchmark
from src.train import load_champion


@pytest.fixture(scope="module")
def results():
    model, _ = load_champion()
    return run_benchmark(model)


def test_latence_d_une_fiche_sous_200_ms(results):
    assert results["single"]["p95_ms"] < 200


def test_volume_quotidien_score_en_moins_de_10_secondes(results):
    """100 000 fiches (plus de 3 jours de volume) en moins de 10 secondes."""
    biggest = results["batch"][-1]
    assert biggest["rows"] == 100_000
    assert biggest["seconds"] < 10


def test_temps_quasi_proportionnel_au_volume(results):
    """Multiplier le volume par 100 ne multiplie pas le temps par beaucoup plus que 100."""
    small, _, big = results["batch"]
    assert big["seconds"] / max(small["seconds"], 1e-3) < 300
