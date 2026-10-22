# Matrice de traçabilité — exigences → code → tests

> Chaque exigence du [cahier des charges](cahier_des_charges.md) est reliée au code qui la
> réalise et au test (ou à la preuve) qui la vérifie. Critère 1.1 du bloc 4.
> Les tests sont lancés automatiquement par la CI à chaque modification.

## Exigences fonctionnelles

| ID | Exigence | Code | Vérification |
|---|---|---|---|
| F1 | Score de suspicion, priorité et version pour 1 à 1 000 fiches | `api/main.py` (`/predict`), `api/schemas.py` | `test_api.py::test_prediction_score_raisons_et_tri`, `test_lot_trop_gros_refuse` |
| F2 | File de revue triée de la plus à la moins suspecte | `api/main.py` (tri), console | `test_prediction_score_raisons_et_tri` |
| F3 | 3 raisons en français par prédiction (SHAP) | `src/explain.py` | `test_model.py::test_explications_lisibles` |
| F4 | État du service, version et mesures du modèle | `/health`, `/model-info` | `test_api.py::test_sante_sans_cle` |
| F5 | Journalisation de chaque prédiction | `api/repository.py` (`log_predictions`) | `test_repository.py::test_journalisation_et_droit_d_acces` |
| F6 | Rapport de dérive (Evidently) | `monitoring/monitor.py`, `monitoring.yml` | `test_monitoring.py::test_scenarios_de_surveillance` ; exécution GitHub du 21/10 (ticket n° 24) |
| F7 | Réentraînement, promotion si meilleur, ≤ 1,5 % de faux positifs et équitable | `retrain/retrain.py`, déclenché automatiquement après alerte par `.github/workflows/monitoring.yml` | `test_apres_un_patch_le_nouveau_modele_est_promu`, `test_sans_changement_on_garde_le_modele_actuel` |

## Critères d'acceptation

| ID | Critère | Code | Vérification |
|---|---|---|---|
| CA-01 | Seuils de performance atteints, meilleur que la règle des signalements | `src/model.py` (`check_acceptance`) | `test_le_modele_en_production_respecte_le_cahier_des_charges` ; `models/cheat_model_v1.json` |
| CA-02 | Robuste aux valeurs manquantes, aberrantes, catégories inconnues | Pipeline (médiane, `handle_unknown`), `src/data.py` (validation) | `test_robuste_aux_valeurs_manquantes_et_inconnues`, `test_robuste_a_un_leger_bruit`, `test_donnees_invalides_refusees_avec_un_message_clair` |
| CA-03 | 3 facteurs explicatifs par prédiction | `src/explain.py` | `test_explications_lisibles`, `test_prediction_score_raisons_et_tri` |
| CA-04 | 422 sur entrée invalide, 401 sans clé | `api/main.py`, `api/schemas.py` | `test_donnees_invalides_refusees_en_francais`, `test_cle_obligatoire` |
| CA-05 | Latence p95 < 200 ms | modèle | `test_temps_de_reponse_inferieur_a_200_ms` |
| CA-06 | Écart de faux positifs entre groupes < 2 points | `src/model.py` (`fairness_report`) | `test_le_modele_est_equitable_entre_groupes` |
| CA-07 | CI verte à chaque modification, image publiée à chaque version | `ci.yml`, `cd.yml` | Historique GitHub Actions ; version `v1.0.0` publiée le 20/10 |
| CA-08 | Aucun secret dans le dépôt | `.env` ignoré, secrets GitHub | `.gitignore`, `.env.example` ; refus de démarrer avec `change-me` |
| CA-09 | La triche humanisée est détectée | `monitoring/monitor.py` (contrôle de performance) | `test_scenarios_de_surveillance[humanisee]` |
| CA-10 | Réentraînement reproductible, promotion conditionnée | `retrain/retrain.py`, `src/model.py` (graine, empreinte, commit) | `test_entrainement_reproductible_et_tracable`, tests de réentraînement |
| CA-11 | Droits d'accès et d'effacement | `api/main.py` (`/players/{id}/data`) | `test_droits_d_acces_et_d_effacement`, `test_effacement_differe_si_triche_confirmee` |

## Exigences non fonctionnelles et transverses

| Exigence | Code | Vérification |
|---|---|---|
| Minimisation : variables d'audit ni dans le modèle ni dans l'API | `src/config.py`, `api/schemas.py` (`extra="forbid"`) | `test_les_variables_d_audit_ne_sont_pas_utilisees`, `test_minimisation_champ_non_prevu_refuse` |
| Pas de fuite de données entre entraînement et test | `src/model.py` (`split_by_player`) | `test_un_joueur_n_est_jamais_a_la_fois_en_entrainement_et_en_test` |
| Limiter les faux positifs à 1 % | `threshold_for_max_fpr` | `test_le_seuil_limite_les_faux_positifs` |
| Sécurité SQL | `api/repository.py` (requêtes paramétrées) | `test_injection_sql_sans_effet` |
| Disponibilité si la base tombe | `api/main.py` | `test_base_en_panne_le_service_repond_quand_meme` |
| Conservation 12 mois | `api/purge.py`, service `purge` | `test_purge_des_predictions_anciennes`, `test_purge_des_decisions_anciennes` |
| Décision humaine contrôlée (article 22) | `/players/{id}/decisions` | `test_decision_humaine_controlee` |
| Console sans ressource externe (CSP) | `api/main.py` (en-têtes) | `test_console_protegee_par_en_tetes_de_securite` |
| Accessibilité de la console | `api/static/console/` | Vérification manuelle : clavier, libellés, contrastes, priorité non portée par la seule couleur |
| Alertes de dérive | `monitoring/monitor.py` (`decide`) | 3 tests de règles d'alerte |
