"""Tests du modèle : méthode d'entraînement, performance, équité, robustesse, rapidité."""

import time

import numpy as np
import pytest

from src.config import FEATURES, MAX_FPR_GAP, TARGET
from src.data import generate_dataset
from src.explain import explain, format_value
from src.model import (
    load_champion,
    save_model,
    set_champion,
    split_by_player,
    threshold_for_max_fpr,
    train,
)


@pytest.fixture(scope="module")
def champion():
    return load_champion()


@pytest.fixture(scope="module")
def fiches():
    return generate_dataset(2_000, seed=99)


def test_un_joueur_n_est_jamais_a_la_fois_en_entrainement_et_en_test():
    train_df, val_df, test_df = split_by_player(generate_dataset(3_000, seed=5), seed=0)
    players = [set(part["player_id"]) for part in (train_df, val_df, test_df)]
    assert not players[0] & players[2] and not players[1] & players[2]


def test_le_seuil_limite_les_faux_positifs():
    rng = np.random.default_rng(0)
    y = (rng.random(5_000) < 0.05).astype(int)
    scores = rng.random(5_000) + y * 0.5
    threshold = threshold_for_max_fpr(y, scores, max_fpr=0.01)
    assert (scores[y == 0] >= threshold).mean() <= 0.01


def test_le_modele_en_production_respecte_le_cahier_des_charges(champion):
    _, meta = champion
    assert meta["acceptance"]["passed"], meta["acceptance"]["details"]
    # Bien meilleur que la règle actuelle (trier par nombre de signalements).
    assert meta["test_metrics"]["precision_top"] > meta["baseline_test_metrics"]["precision_top"]


def test_le_modele_est_equitable_entre_groupes(champion):
    for group, report in champion[1]["fairness"].items():
        assert report["gap"] < MAX_FPR_GAP, group


def test_entrainement_reproductible_et_tracable(tmp_path):
    df = generate_dataset(8_000, seed=7)
    model, info = train(df, seed=7)
    _, info_again = train(df, seed=7)
    assert info["threshold"] == info_again["threshold"]  # même graine, même résultat
    save_model(model, info, "v1", seed=7, models_dir=tmp_path)
    _, meta = load_champion(tmp_path)
    assert meta["data"]["fingerprint"] and meta["git_commit"] and meta["seed"] == 7
    assert "player_id" not in (tmp_path / "reference_v1.csv").read_text().splitlines()[0]
    with pytest.raises(FileNotFoundError):
        set_champion("v9", tmp_path)


def test_robuste_aux_valeurs_manquantes_et_inconnues(champion, fiches):
    model, _ = champion
    X = fiches[FEATURES].head(50).copy()
    X.loc[X.index[:10], "avg_reaction_ms"] = np.nan  # télémétrie perdue
    X.loc[X.index[10:20], "platform"] = "cloud"  # plateforme jamais vue
    scores = model.predict_proba(X)[:, 1]
    assert np.isfinite(scores).all()


def test_robuste_a_un_leger_bruit(champion, fiches):
    """Un bruit de mesure de 1 % ne doit pas bouleverser le classement des fiches."""
    model, _ = champion
    X = fiches[FEATURES]
    noisy = X.copy()
    noisy["accuracy"] = (X["accuracy"] * 1.01).clip(0, 1)
    top = set(np.argsort(-model.predict_proba(X)[:, 1])[:50])
    top_noisy = set(np.argsort(-model.predict_proba(noisy)[:, 1])[:50])
    assert len(top & top_noisy) >= 40


def test_temps_de_reponse_inferieur_a_200_ms(champion, fiches):
    model, meta = champion
    one = fiches[FEATURES].head(1)
    durations = []
    for _ in range(30):
        start = time.perf_counter()
        model.predict_proba(one)
        durations.append(time.perf_counter() - start)
    assert np.percentile(durations, 95) < 0.2


def test_explications_lisibles(champion, fiches):
    pytest.importorskip("shap")
    model, meta = champion
    reasons = explain(model, fiches[FEATURES].head(3), meta["explain_info"])
    assert len(reasons) == 3 and all(len(r) == 3 for r in reasons)
    assert "risque" in reasons[0][0]["text"]
    assert format_value("accuracy", 0.31) == "31 %"
    assert format_value("avg_reaction_ms", float("nan")) == "non mesuré"


def test_les_variables_d_audit_ne_sont_pas_utilisees(champion):
    _, meta = champion
    assert "age_band" not in meta["features"] and "accessibility_mode" not in meta["features"]
    assert TARGET not in meta["features"]
