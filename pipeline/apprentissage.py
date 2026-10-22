"""Appariement LiDAR ↔ inventaire, entraînement et validation des modèles (genre et circonférence)."""
from __future__ import annotations

import logging

import numpy as np
from pyproj import Transformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, mean_absolute_error,
                             r2_score)
from sklearn.model_selection import GroupKFold

from config import MIN_ECHANTILLONS_GENRE, TAILLE_BLOC_VALIDATION

log = logging.getLogger(__name__)
WGS84_VERS_L93 = Transformer.from_crs(4326, 2154, always_xy=True)

VARIABLES = ["hauteur", "h_p90", "h_p75", "h_p50", "h_p25", "h_p10", "h_moy", "h_ecart", "rapport_base",
             "entropie", "surface", "diametre", "allongement", "compacite", "densite", "int_moy",
             "int_ecart", "int_p90", "part_premiers", "part_uniques", "retours_moy", "volume",
             "transparence", "int_derniers", "asymetrie", "aplatissement", "part_haut"]

NOMS_VARIABLES = {
    "hauteur": "Hauteur", "h_p90": "Hauteur P90", "h_p75": "Hauteur P75", "h_p50": "Hauteur médiane",
    "h_p25": "Hauteur P25", "h_p10": "Base du houppier (P10)", "h_moy": "Hauteur moyenne",
    "h_ecart": "Dispersion verticale", "rapport_base": "Rapport base / sommet", "entropie": "Entropie verticale",
    "surface": "Surface du houppier", "diametre": "Diamètre du houppier", "allongement": "Allongement",
    "compacite": "Compacité", "densite": "Densité de points", "int_moy": "Intensité moyenne",
    "int_ecart": "Dispersion de l'intensité", "int_p90": "Intensité P90", "part_premiers": "Part de premiers retours",
    "part_uniques": "Part de retours uniques", "retours_moy": "Nombre moyen de retours", "volume": "Volume du houppier",
    "transparence": "Transparence hivernale du houppier", "int_derniers": "Intensité des derniers retours",
    "asymetrie": "Asymétrie verticale", "aplatissement": "Aplatissement vertical", "part_haut": "Part de points dans la moitié haute",
}


def apparier(arbres_lidar: dict[int, dict], inventaire: dict, etiquettes, grille) -> dict[int, dict]:
    """Associe à chaque houppier LiDAR l'arbre inventorié qui s'y trouve (le plus proche de la cime)."""
    candidats: dict[int, list] = {}
    for f in inventaire.get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        if g.get("type") != "Point" or not p.get("genre"):
            continue
        x, y = WGS84_VERS_L93.transform(*g["coordinates"][:2])
        l, c = grille.indices(np.array([x]), np.array([y]))
        i = int(etiquettes[l[0], c[0]])
        if i in arbres_lidar:
            a = arbres_lidar[i]
            candidats.setdefault(i, []).append(((x - a["x"]) ** 2 + (y - a["y"]) ** 2, p))
    paires = {}
    for i, liste in candidats.items():
        _, p = min(liste, key=lambda t: t[0])
        paires[i] = {
            "genre": str(p.get("genre")).strip().capitalize(),
            "libelle": p.get("libellefrancais"),
            "espece": p.get("espece"),
            "hauteur": p.get("hauteurenm") or None,
            "circonference": p.get("circonferenceencm") or None,
            "domanialite": p.get("domanialite"),
            "nb_dans_houppier": len(liste),
        }
    log.info("%d houppiers appariés à un arbre de l'inventaire", len(paires))
    return paires


def _matrice(arbres, ids):
    return np.array([[arbres[i][v] for v in VARIABLES] for i in ids], dtype=np.float32)


def _blocs(arbres, ids):
    return np.array([f"{int(arbres[i]['x'] // TAILLE_BLOC_VALIDATION)}_{int(arbres[i]['y'] // TAILLE_BLOC_VALIDATION)}"
                     for i in ids])


def entrainer(arbres: dict[int, dict], paires: dict[int, dict]):
    """Classification du genre et régression de la circonférence, validées par blocs spatiaux."""
    metriques: dict = {}

    # --- Genre -----------------------------------------------------------------------------
    ids = [i for i in paires if paires[i]["nb_dans_houppier"] <= 2]  # houppiers « purs »
    genres = np.array([paires[i]["genre"] for i in ids])
    valeurs, comptes = np.unique(genres, return_counts=True)
    retenus = set(valeurs[comptes >= MIN_ECHANTILLONS_GENRE])
    y = np.array([g if g in retenus else "Autre" for g in genres])
    X = _matrice(arbres, ids)
    groupes = _blocs(arbres, ids)
    classes = sorted(set(y), key=lambda g: (g == "Autre", -np.sum(y == g)))
    log.info("Genres modélisés : %s", ", ".join(f"{g} ({np.sum(y == g)})" for g in classes))

    modele = RandomForestClassifier(n_estimators=400, min_samples_leaf=2, class_weight="balanced",
                                    random_state=42, n_jobs=-1)
    n_plis = min(5, len(set(groupes)))
    pred = np.empty_like(y)
    for app, test in GroupKFold(n_splits=n_plis).split(X, y, groupes):
        modele.fit(X[app], y[app])
        pred[test] = modele.predict(X[test])
    base = max(np.mean(y == g) for g in classes)  # précision d'un modèle qui répondrait toujours la classe majoritaire
    metriques["genre"] = {
        "n_echantillons": int(len(y)),
        "classes": classes,
        "effectifs": {g: int(np.sum(y == g)) for g in classes},
        "precision_globale": round(float(accuracy_score(y, pred)), 3),
        "f1_macro": round(float(f1_score(y, pred, average="macro")), 3),
        "precision_hasard": round(float(base), 3),
        "f1_par_classe": {g: round(float(s), 3) for g, s in
                          zip(classes, f1_score(y, pred, labels=classes, average=None))},
        "matrice_confusion": confusion_matrix(y, pred, labels=classes).tolist(),
        "validation": f"Validation croisée spatiale : {n_plis} plis, blocs de {TAILLE_BLOC_VALIDATION} m "
                      "(les arbres testés sont dans des blocs jamais vus à l'entraînement)",
    }
    modele.fit(X, y)
    metriques["importance_variables"] = sorted(
        [{"variable": NOMS_VARIABLES[v], "importance": round(float(s), 4)} for v, s in zip(VARIABLES, modele.feature_importances_)],
        key=lambda d: -d["importance"])[:10]
    log.info("Genre : précision %.1f %% (classe majoritaire %.1f %%), F1 macro %.2f",
             100 * metriques["genre"]["precision_globale"], 100 * base, metriques["genre"]["f1_macro"])

    # --- Circonférence ---------------------------------------------------------------------
    ids_c = [i for i in ids if (paires[i]["circonference"] or 0) > 10]
    Xc, yc = _matrice(arbres, ids_c), np.array([paires[i]["circonference"] for i in ids_c], dtype=float)
    regresseur = RandomForestRegressor(n_estimators=400, min_samples_leaf=3, random_state=42, n_jobs=-1)
    pc = np.zeros_like(yc)
    gc = _blocs(arbres, ids_c)
    for app, test in GroupKFold(n_splits=min(5, len(set(gc)))).split(Xc, yc, gc):
        regresseur.fit(Xc[app], yc[app])
        pc[test] = regresseur.predict(Xc[test])
    metriques["circonference"] = {
        "n_echantillons": int(len(yc)),
        "mae_cm": round(float(mean_absolute_error(yc, pc)), 1),
        "r2": round(float(r2_score(yc, pc)), 3),
        "moyenne_cm": round(float(yc.mean()), 1),
    }
    regresseur.fit(Xc, yc)
    log.info("Circonférence : erreur moyenne %.0f cm, R² %.2f", metriques["circonference"]["mae_cm"],
             metriques["circonference"]["r2"])

    # --- Hauteur LiDAR vs hauteur inventaire ------------------------------------------------
    ids_h = [i for i in paires if (paires[i]["hauteur"] or 0) > 0]
    if ids_h:
        hl = np.array([arbres[i]["hauteur"] for i in ids_h])
        hi = np.array([paires[i]["hauteur"] for i in ids_h], dtype=float)
        metriques["hauteur"] = {
            "n_echantillons": len(ids_h),
            "ecart_moyen_m": round(float(np.mean(np.abs(hl - hi))), 2),
            "biais_m": round(float(np.mean(hl - hi)), 2),
            "correlation": round(float(np.corrcoef(hl, hi)[0, 1]), 3),
        }

    # --- Prédictions pour tous les arbres détectés -------------------------------------------
    tous = list(arbres)
    Xt = _matrice(arbres, tous)
    probas = modele.predict_proba(Xt)
    circ = regresseur.predict(Xt)
    predictions = {}
    for k, i in enumerate(tous):
        j = int(np.argmax(probas[k]))
        predictions[i] = {"genre": str(modele.classes_[j]), "confiance": round(float(probas[k][j]), 2),
                          "circonference": int(round(circ[k]))}
    return predictions, metriques
