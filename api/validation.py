"""Validation ligne par ligne de profils importés (console de modération).

/predict/batch refuse un lot entier dès qu'une ligne est invalide. Pour un import de
fichier, le modérateur a besoin de savoir QUELLES lignes posent problème et POURQUOI :
ce module applique le même schéma (MatchStats) ligne par ligne et traduit les erreurs
en français. Les lignes valides peuvent ensuite être scorées.
"""

from pydantic import ValidationError

from api.schemas import MatchStats

# Libellés français des types d'erreurs Pydantic les plus courants.
ERROR_MESSAGES = {
    "missing": "champ obligatoire manquant",
    "extra_forbidden": "champ non autorisé (donnée non collectée par Sentinel)",
    "uuid_parsing": "identifiant invalide (format UUID attendu)",
    "uuid_type": "identifiant invalide (format UUID attendu)",
    "float_parsing": "nombre attendu",
    "float_type": "nombre attendu",
    "int_parsing": "nombre entier attendu",
    "int_type": "nombre entier attendu",
    "int_from_float": "nombre entier attendu",
    "literal_error": "valeur non autorisée",
}


def french_message(error: dict) -> str:
    """Transforme une erreur Pydantic en phrase lisible : '<champ> : <problème>'."""
    field = ".".join(str(part) for part in error["loc"]) or "ligne"
    kind = error["type"]
    context = error.get("ctx", {})
    if error.get("input") is None and kind not in ("missing", "extra_forbidden"):
        problem = "valeur manquante"
    elif kind == "greater_than_equal":
        problem = f"doit être supérieur ou égal à {context.get('ge')}"
    elif kind == "less_than_equal":
        problem = f"doit être inférieur ou égal à {context.get('le')}"
    elif kind == "literal_error":
        expected = str(context.get("expected", "?")).replace(" or ", " ou ")
        problem = f"valeur non autorisée (attendu : {expected})"
    else:
        problem = ERROR_MESSAGES.get(kind, error["msg"])
    return f"{field} : {problem}"


def validate_rows(rows: list[dict]) -> dict:
    """Valide chaque ligne et renvoie un rapport détaillé."""
    results = []
    for number, raw in enumerate(rows, start=1):
        # Une cellule vide dans un CSV signifie "valeur absente".
        cleaned = {key: (None if value == "" else value) for key, value in raw.items()}
        try:
            MatchStats.model_validate(cleaned)
            results.append({"row": number, "valid": True, "errors": []})
        except ValidationError as error:
            messages = [french_message(e) for e in error.errors()]
            results.append({"row": number, "valid": False, "errors": messages})
    valid_count = sum(r["valid"] for r in results)
    return {
        "total": len(results),
        "valid_count": valid_count,
        "invalid_count": len(results) - valid_count,
        "rows": results,
    }
