"""Téléchargement des données : nuage de points LiDAR HD (IGN) et inventaire des arbres (Ville de Paris)."""
from __future__ import annotations

import json
import logging

import laspy
import numpy as np
import requests
from pyproj import Transformer

from config import API_ARBRES, CACHE, COUCHES_DALLES, WFS_IGN, ZONE

log = logging.getLogger(__name__)
L93_VERS_WGS84 = Transformer.from_crs(2154, 4326, always_xy=True)


def _couches_lidar_du_catalogue() -> list[str]:
    """Liste les couches du WFS IGN dont le nom évoque le LiDAR HD (au cas où les noms connus changent)."""
    try:
        r = requests.get(WFS_IGN, params={"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities"}, timeout=90)
        r.raise_for_status()
    except Exception as exc:
        log.warning("Catalogue WFS indisponible : %s", exc)
        return []
    import re
    noms = re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", r.text)
    lidar = [n for n in noms if re.search(r"lidar|nuage|nualid", n, re.I)]
    log.info("Couches LiDAR du catalogue WFS : %s", lidar)
    return lidar


def lister_dalles() -> list[dict]:
    """Interroge le tableau d'assemblage LiDAR HD (WFS IGN) et renvoie les dalles qui couvrent la zone."""
    lon0, lat0 = L93_VERS_WGS84.transform(ZONE["xmin"], ZONE["ymin"])
    lon1, lat1 = L93_VERS_WGS84.transform(ZONE["xmax"], ZONE["ymax"])
    emprises = [
        f"{ZONE['xmin']},{ZONE['ymin']},{ZONE['xmax']},{ZONE['ymax']},urn:ogc:def:crs:EPSG::2154",
        f"{lat0},{lon0},{lat1},{lon1},urn:ogc:def:crs:EPSG::4326",
    ]
    couches = COUCHES_DALLES + [c for c in _couches_lidar_du_catalogue() if c not in COUCHES_DALLES]
    essais = [(c, b) for c in couches for b in emprises]
    for couche, bbox in essais:
        params = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": couche, "OUTPUTFORMAT": "application/json", "BBOX": bbox, "COUNT": 50,
        }
        try:
            r = requests.get(WFS_IGN, params=params, timeout=60)
            r.raise_for_status()
            entites = r.json().get("features", [])
        except Exception as exc:  # couche absente ou format inattendu : on essaie la suivante
            log.warning("Couche %s indisponible : %s", couche, str(exc)[:120])
            continue
        if entites:
            log.info("Couche %s : attributs %s", couche, entites[0].get("properties"))
        dalles = []
        for f in entites:
            p = f.get("properties", {})
            url = next((v for k, v in p.items() if isinstance(v, str) and v.startswith("http") and "laz" in v.lower()), None)
            if url:
                dalles.append({"nom": p.get("name") or p.get("nom") or url.rsplit("/", 1)[-1], "url": url})
        if dalles:
            log.info("%d dalle(s) LiDAR HD trouvée(s) via %s", len(dalles), couche)
            for d in dalles:
                log.info("  %s", d["nom"])
            return dalles
        log.warning("Couche %s : aucune URL de dalle dans les attributs %s", couche,
                    list(entites[0]["properties"]) if entites else "(aucune entité)")
    raise RuntimeError("Impossible de lister les dalles LiDAR HD")


def charger_points(dalles: list[dict]) -> dict[str, np.ndarray]:
    """Télécharge chaque dalle LiDAR HD et ne garde que les points de la zone d'étude."""
    cache = CACHE / "points.npz"
    if cache.exists():
        log.info("Nuage de points lu depuis le cache")
        return dict(np.load(cache))

    morceaux = []
    CACHE.mkdir(parents=True, exist_ok=True)
    for d in dalles:
        fichier = CACHE / d["nom"]
        log.info("Téléchargement de %s", d["nom"])
        with requests.get(d["url"], stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(fichier, "wb") as f:
                for bloc in r.iter_content(chunk_size=1 << 22):
                    f.write(bloc)
        log.info("  %.0f Mo", fichier.stat().st_size / 1e6)
        with laspy.open(fichier) as lecteur:
            for pts in lecteur.chunk_iterator(5_000_000):
                x, y = np.asarray(pts.x), np.asarray(pts.y)
                garde = (x >= ZONE["xmin"]) & (x < ZONE["xmax"]) & (y >= ZONE["ymin"]) & (y < ZONE["ymax"])
                if not garde.any():
                    continue
                morceaux.append({
                    "x": x[garde].astype(np.float64),
                    "y": y[garde].astype(np.float64),
                    "z": np.asarray(pts.z)[garde].astype(np.float32),
                    "classe": np.asarray(pts.classification)[garde].astype(np.uint8),
                    "intensite": np.asarray(pts.intensity)[garde].astype(np.uint16),
                    "retour": np.asarray(pts.return_number)[garde].astype(np.uint8),
                    "nb_retours": np.asarray(pts.number_of_returns)[garde].astype(np.uint8),
                })
        fichier.unlink()  # on ne garde que les points de la zone
    if not morceaux:
        raise RuntimeError("Aucun point LiDAR dans la zone")
    points = {k: np.concatenate([m[k] for m in morceaux]) for k in morceaux[0]}
    np.savez_compressed(cache, **points)
    log.info("Total : %d points", len(points["x"]))
    return points


def charger_arbres_paris() -> dict:
    """Arbres de l'inventaire de la Ville de Paris situés dans la zone (GeoJSON WGS84)."""
    cache = CACHE / "arbres_paris.geojson"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    lon0, lat0 = L93_VERS_WGS84.transform(ZONE["xmin"], ZONE["ymin"])
    lon1, lat1 = L93_VERS_WGS84.transform(ZONE["xmax"], ZONE["ymax"])
    params = {"where": f"in_bbox(geo_point_2d, {lat0}, {lon0}, {lat1}, {lon1})"}
    r = requests.get(API_ARBRES, params=params, timeout=120)
    r.raise_for_status()
    geojson = r.json()
    log.info("%d arbres de l'inventaire parisien dans la zone", len(geojson.get("features", [])))
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(geojson), encoding="utf-8")
    return geojson
