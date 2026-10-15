"""Tests de l'explicabilité (src/explain.py) et de l'audit d'équité (src/fairness.py).

Les tests marqués "SHAP" ne s'exécutent que si la bibliothèque shap est installée.

Lancer : pytest tests/test_explain_fairness.py -v
"""

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src.config import FEATURES, MAX_FPR_GAP, TARGET
from src.data.generate import generate_dataset
from src.explain import (
    _original_feature,
    build_reason,
    compute_contributions,
    explain,
    format_value,
    reference_by_rank,
    top_reasons,
    transformed_mean,
)
from src.fairness import fairness_passed, fairness_report, group_rates
from src.features import build_preprocessor
from src.train import train_and_select


@pytest.fixture(scope="module")
def data():
    return generate_dataset(n_matches=8_000, seed=3)


@pytest.fixture(scope="module")
def linear_model(data):
    """Petit modèle linéaire : son explication exacte se vérifie sans SHAP."""
    model = Pipeline(
        [
            ("preprocessing", build_preprocessor(scale_numeric=True)),
            ("model", LogisticRegression(max_iter=1000)),
        ]
    )
    return model.fit(data[FEATURES], data[TARGET])


# --- Mise en forme des explications --------------------------------------------------


@pytest.mark.parametrize(
    "feature, value, expected",
    [
        ("accuracy", 0.273, "27 %"),
        ("avg_reaction_ms", 112.4, "112 ms"),
        ("kd_ratio", 1.5, "1.50"),
        ("account_age_days", 30, "30 jours"),
        ("input_device", "clavier_souris", "clavier-souris"),
        ("avg_reaction_ms", float("nan"), "non mesuré"),
    ],
)
def test_format_value(feature, value, expected):
    assert format_value(feature, value) == expected


def test_phrase_complete_avec_reference():
    reason = build_reason("avg_reaction_ms", 112.0, contribution=0.8, reference=262.0)
    assert reason["text"] == (
        "Temps de réaction moyen : 112 ms (joueurs honnêtes de son rang : 262 ms)"
        " — augmente le risque"
    )
    assert reason["direction"] == "hausse"


def test_phrase_categorie_sans_reference():
    reason = build_reason("input_device", "manette", contribution=-0.3, reference=None)
    assert reason["text"] == "Périphérique : manette — diminue le risque"


def test_top_reasons_trie_par_importance_absolue():
    row = pd.Series({f: 0 for f in FEATURES} | {"rank_tier": 5})
    contributions = pd.Series({f: 0.0 for f in FEATURES})
    contributions["headshot_rate"] = 0.5
    contributions["account_age_days"] = -0.9
    contributions["accuracy"] = 0.2
    reasons = top_reasons(row, contributions, reference_stats={}, top_n=3)
    assert [r["feature"] for r in reasons] == ["account_age_days", "headshot_rate", "accuracy"]


def test_retour_a_la_variable_d_origine():
    assert _original_feature("num__accuracy") == "accuracy"
    assert _original_feature("cat__input_device_manette") == "input_device"
    assert _original_feature("cat__platform_pc") == "platform"


def test_references_calculees_sur_les_honnetes_uniquement(data):
    refs = reference_by_rank(data)
    honest_rank5 = data[(data[TARGET] == 0) & (data["rank_tier"] == 5)]
    assert refs["5"]["headshot_rate"] == pytest.approx(
        honest_rank5["headshot_rate"].median(), abs=1e-3
    )


# --- Contributions : propriété d'additivité ------------------------------------------


def test_contributions_lineaires_additives(linear_model, data):
    """Somme des contributions + score du joueur moyen = score du joueur (exactement)."""
    X = data.head(50)
    mean = transformed_mean(linear_model, data)
    contributions = compute_contributions(linear_model, X, background_mean=mean)
    classifier = linear_model.named_steps["model"]
    mean_score = classifier.intercept_[0] + classifier.coef_[0] @ np.asarray(mean)
    np.testing.assert_allclose(
        mean_score + contributions.sum(axis=1), linear_model.decision_function(X[FEATURES])
    )
    assert list(contributions.columns) == FEATURES


def test_explain_donne_trois_raisons_par_fiche(linear_model, data):
    info = {
        "reference_by_rank": reference_by_rank(data),
        "background_mean": transformed_mean(linear_model, data),
    }
    reasons = explain(linear_model, data.head(5), info)
    assert len(reasons) == 5
    assert all(len(r) == 3 for r in reasons)
    assert all(isinstance(reason["text"], str) for r in reasons for reason in r)


def test_modele_lineaire_sans_moyenne_refuse(linear_model, data):
    with pytest.raises(ValueError, match="background_mean"):
        compute_contributions(linear_model, data.head(2))


def test_shap_additivite_gradient_boosting():
    """SHAP : valeur de base + somme des contributions = score brut du modèle à arbres."""
    shap = pytest.importorskip("shap")
    df = generate_dataset(n_matches=20_000, seed=5)
    result = train_and_select(df, seed=5)
    model = result.model
    if model.named_steps["model"].__class__.__name__ != "HistGradientBoostingClassifier":
        pytest.skip("Le modèle retenu n'est pas un modèle à arbres.")

    X = df.head(30)
    contributions = compute_contributions(model, X)
    explainer = shap.TreeExplainer(model.named_steps["model"])
    base_value = np.ravel(explainer.expected_value)[-1]
    np.testing.assert_allclose(
        base_value + contributions.sum(axis=1),
        model.named_steps["model"].decision_function(
            model.named_steps["preprocessing"].transform(X[FEATURES])
        ),
        atol=1e-3,
    )


def test_shap_les_tricheurs_flagrants_sont_expliques_par_des_hausses():
    """Pour les fiches les plus suspectes, la 1re raison doit augmenter le risque."""
    pytest.importorskip("shap")
    df = generate_dataset(n_matches=20_000, seed=5)
    result = train_and_select(df, seed=5)
    scores = result.model.predict_proba(df[FEATURES])[:, 1]
    most_suspect = df.iloc[np.argsort(-scores)[:10]]
    reasons = explain(result.model, most_suspect, result.explain_info)
    assert all(r[0]["direction"] == "hausse" for r in reasons)


# --- Audit d'équité -------------------------------------------------------------------


def _toy_frame():
    """10 honnêtes par groupe ; le groupe "manette" a 2 faux positifs, l'autre 1."""
    return pd.DataFrame(
        {
            "input_device": ["manette"] * 10 + ["clavier_souris"] * 10,
            TARGET: [0] * 20,
        }
    )


def test_taux_de_faux_positifs_par_groupe():
    df = _toy_frame()
    flagged = np.array([True, True] + [False] * 8 + [True] + [False] * 9)
    rates = group_rates(df, flagged, "input_device")
    assert rates["manette"]["false_positive_rate"] == 0.2
    assert rates["clavier_souris"]["false_positive_rate"] == 0.1
    assert rates["manette"]["recall"] is None  # aucun tricheur dans le groupe


def test_rapport_d_equite_sur_le_modele():
    result = train_and_select(generate_dataset(n_matches=50_000, seed=42), seed=42)
    for group, report in result.fairness.items():
        assert report["fpr_gap"] < MAX_FPR_GAP, f"écart trop grand pour {group}"
    assert fairness_passed(result.fairness)
    assert result.acceptance["details"]["fairness"] is True


def test_groupe_a_faible_effectif_ignore_dans_l_ecart():
    """Un groupe de moins de 100 honnêtes est signalé mais n'entre pas dans le calcul."""
    df = pd.DataFrame(
        {
            "input_device": ["manette"] * 200 + ["clavier_souris"] * 200,
            "platform": ["pc"] * 400,
            "accessibility_mode": [False] * 395 + [True] * 5,
            "age_band": ["18-24"] * 400,
            TARGET: [0] * 400,
        }
    )
    scores = np.zeros(400)
    scores[-5:] = 1.0  # les 5 joueurs "accessibilité" sont tous signalés
    report = fairness_report(df, scores, threshold=0.5)
    assert report["accessibility_mode"]["rates"]["True"]["reliable"] is False
    assert report["accessibility_mode"]["passed"] is True
