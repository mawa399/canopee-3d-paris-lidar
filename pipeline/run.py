"""Pipeline complet : LiDAR HD + inventaire → arbres segmentés, genre prédit, fichiers pour l'application web.

Usage : python pipeline/run.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date

import numpy as np
from pyproj import Transformer
from rasterio import features as rfeatures
from shapely.geometry import mapping, shape
from shapely.ops import transform as stransform

from apprentissage import apparier, entrainer
from config import NOM_ZONE, SORTIE, ZONE
from telechargement import charger_arbres_paris, charger_points, lister_dalles
from traitement import VEGETATION, Grille, caracteristiques, modele_terrain_et_canopee, segmenter_arbres

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("pipeline")
VERS_WGS84 = Transformer.from_crs(2154, 4326, always_xy=True)
MAX_POINTS_PAR_ARBRE = 400


def exporter_houppiers(etiquettes, ids_gardes, grille):
    """Polygones des houppiers (WGS84), simplifiés."""
    masque = np.isin(etiquettes, list(ids_gardes))
    entites = []
    for geom, val in rfeatures.shapes(etiquettes.astype(np.int32), mask=masque, transform=grille.transform()):
        poly = shape(geom).simplify(0.35, preserve_topology=True)
        if poly.is_empty:
            continue
        poly = stransform(lambda x, y, z=None: VERS_WGS84.transform(x, y), poly)
        entites.append({"type": "Feature", "geometry": mapping(poly), "properties": {"id": int(val)}})
    return entites


def exporter_nuages(points, hauteur, etiquettes, arbres, grille):
    """Points LiDAR de chaque arbre (sous-échantillonnés), en binaire compact : int16 dx, dy, h en décimètres."""
    l, c = grille.indices(points["x"], points["y"])
    lab = etiquettes[l, c]
    sel = np.isin(points["classe"], VEGETATION) & (lab > 0) & (hauteur > 0.5)
    idx = np.nonzero(sel)[0]
    idx = idx[np.argsort(lab[idx], kind="stable")]
    labs = lab[idx]
    rng = np.random.default_rng(0)
    morceaux, index, decalage = [], {}, 0
    for i in arbres:
        d, f = np.searchsorted(labs, i), np.searchsorted(labs, i, side="right")
        if f <= d:
            continue
        choix = idx[d:f]
        if len(choix) > MAX_POINTS_PAR_ARBRE:
            choix = rng.choice(choix, MAX_POINTS_PAR_ARBRE, replace=False)
        a = arbres[i]
        tableau = np.stack([
            np.round((points["x"][choix] - a["x"]) * 10),
            np.round((points["y"][choix] - a["y"]) * 10),
            np.round(hauteur[choix] * 10),
        ], axis=1).clip(-32000, 32000).astype(np.int16)
        morceaux.append(tableau)
        index[int(i)] = [decalage, len(tableau)]
        decalage += len(tableau)
    binaire = np.concatenate(morceaux).tobytes() if morceaux else b""
    return binaire, index


def main():
    t0 = time.time()
    SORTIE.mkdir(parents=True, exist_ok=True)

    dalles = lister_dalles()
    points = charger_points(dalles)
    inventaire = charger_arbres_paris()

    grille = Grille()
    mnt, mnh, hauteur = modele_terrain_et_canopee(points, grille)
    etiquettes, ids = segmenter_arbres(mnh, grille)
    arbres = caracteristiques(points, hauteur, etiquettes, ids, mnh, grille)
    paires = apparier(arbres, inventaire, etiquettes, grille)
    predictions, metriques = entrainer(arbres, paires)

    # Arbres (points au niveau de la cime)
    entites = []
    for i, a in arbres.items():
        lon, lat = VERS_WGS84.transform(a["x"], a["y"])
        p, obs = predictions[i], paires.get(i, {})
        entites.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
            "properties": {
                "id": i,
                "hauteur": round(a["hauteur"], 1),
                "diametre": round(a["diametre"], 1),
                "surface": round(a["surface"], 1),
                "genre_predit": p["genre"],
                "confiance": p["confiance"],
                "circ_predite": p["circonference"],
                "apparie": bool(obs),
                "genre_obs": obs.get("genre"),
                "libelle_obs": obs.get("libelle"),
                "espece_obs": obs.get("espece"),
                "hauteur_obs": obs.get("hauteur"),
                "circ_obs": obs.get("circonference"),
                "domanialite": obs.get("domanialite"),
            },
        })
    (SORTIE / "arbres.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": entites}), encoding="utf-8")

    houppiers = exporter_houppiers(etiquettes, set(arbres), grille)
    (SORTIE / "houppiers.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": houppiers}), encoding="utf-8")

    binaire, index = exporter_nuages(points, hauteur, etiquettes, arbres, grille)
    (SORTIE / "nuages.bin").write_bytes(binaire)
    (SORTIE / "nuages_index.json").write_text(json.dumps(index), encoding="utf-8")

    # Synthèse de la zone
    lon0, lat0 = VERS_WGS84.transform(ZONE["xmin"], ZONE["ymin"])
    lon1, lat1 = VERS_WGS84.transform(ZONE["xmax"], ZONE["ymax"])
    surface_zone = (ZONE["xmax"] - ZONE["xmin"]) * (ZONE["ymax"] - ZONE["ymin"])
    metriques["zone"] = {
        "nom": NOM_ZONE,
        "emprise_wgs84": [lon0, lat0, lon1, lat1],
        "surface_ha": round(surface_zone / 1e4, 1),
        "nb_points_lidar": int(len(points["x"])),
        "nb_arbres_detectes": len(arbres),
        "nb_arbres_inventaire": len(inventaire.get("features", [])),
        "nb_apparies": len(paires),
        "taux_canopee": round(float((mnh > 2.5).mean()), 3),
        "hauteur_moyenne": round(float(np.mean([a["hauteur"] for a in arbres.values()])), 1),
        "dalles": [d["nom"] for d in dalles],
        "date_traitement": date.today().isoformat(),
        "duree_s": round(time.time() - t0),
    }
    (SORTIE / "metriques.json").write_text(json.dumps(metriques, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Terminé en %d s : %s", time.time() - t0, json.dumps(metriques["zone"], ensure_ascii=False))
    print(json.dumps({k: metriques[k] for k in ("genre", "circonference", "hauteur") if k in metriques},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
