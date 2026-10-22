"""Traitement du nuage de points : MNT, modèle de hauteur de canopée, détection et segmentation des arbres."""
from __future__ import annotations

import logging

import numpy as np
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.segmentation import watershed

from config import (DISTANCE_MIN_CIMES, HAUTEUR_MIN_ARBRE, HAUTEUR_MIN_HOUPPIER, RESOLUTION,
                    SURFACE_MIN_HOUPPIER, ZONE)

log = logging.getLogger(__name__)

SOL, VEG_HAUTE = 2, 5
VEGETATION = (3, 4, 5)


class Grille:
    """Grille raster alignée sur la zone d'étude (origine en haut à gauche)."""

    def __init__(self, res: float = RESOLUTION):
        self.res = res
        self.x0, self.y1 = ZONE["xmin"], ZONE["ymax"]
        self.nc = int(np.ceil((ZONE["xmax"] - ZONE["xmin"]) / res))
        self.nl = int(np.ceil((ZONE["ymax"] - ZONE["ymin"]) / res))

    def indices(self, x, y):
        c = np.clip(((x - self.x0) / self.res).astype(int), 0, self.nc - 1)
        l = np.clip(((self.y1 - y) / self.res).astype(int), 0, self.nl - 1)
        return l, c

    def centre(self, l, c):
        return self.x0 + (c + 0.5) * self.res, self.y1 - (l + 0.5) * self.res

    def transform(self):
        """Transformation affine au format rasterio (a, b, c, d, e, f)."""
        from rasterio.transform import Affine
        return Affine(self.res, 0, self.x0, 0, -self.res, self.y1)


def _agreger(grille, l, c, valeurs, fonction):
    """Valeur min ou max par cellule (NaN si cellule vide)."""
    raster = np.full((grille.nl, grille.nc), np.nan, dtype=np.float32)
    plat = l * grille.nc + c
    ordre = np.argsort(valeurs) if fonction == "max" else np.argsort(-valeurs)
    # en écrivant dans l'ordre croissant (resp. décroissant), la dernière valeur écrite est le max (resp. min)
    raster.ravel()[plat[ordre]] = valeurs[ordre]
    return raster


def _boucher(raster):
    """Remplit les cellules vides avec la valeur de la cellule renseignée la plus proche."""
    vide = np.isnan(raster)
    if not vide.any():
        return raster
    _, (il, ic) = ndi.distance_transform_edt(vide, return_indices=True)
    return raster[il, ic]


def modele_terrain_et_canopee(points: dict, grille: Grille):
    """Calcule le MNT (sol) et le modèle numérique de hauteur de la végétation haute (MNH)."""
    l, c = grille.indices(points["x"], points["y"])
    z = points["z"].astype(np.float32)
    classe = points["classe"]

    sol = classe == SOL
    if sol.sum() < 100:
        raise RuntimeError("Trop peu de points sol pour calculer le MNT")
    mnt = _boucher(_agreger(grille, l[sol], c[sol], z[sol], "min"))
    mnt = ndi.gaussian_filter(mnt, 1.0)

    hauteur = z - mnt[l, c]
    veg = classe == VEG_HAUTE
    mnh = _agreger(grille, l[veg], c[veg], hauteur[veg], "max")
    mnh = np.nan_to_num(mnh, nan=0.0)
    mnh = ndi.grey_closing(mnh, size=3)        # bouche les petits trous dans les houppiers
    mnh = np.clip(ndi.gaussian_filter(mnh, 0.8), 0, None)
    log.info("MNT %.1f–%.1f m, canopée max %.1f m", np.nanmin(mnt), np.nanmax(mnt), mnh.max())
    return mnt, mnh, hauteur


def segmenter_arbres(mnh: np.ndarray, grille: Grille):
    """Détecte les cimes (maxima locaux) puis délimite chaque houppier par ligne de partage des eaux."""
    lisse = ndi.gaussian_filter(mnh, 1.0)
    cimes = peak_local_max(
        lisse,
        min_distance=max(1, int(DISTANCE_MIN_CIMES / grille.res)),
        threshold_abs=HAUTEUR_MIN_ARBRE,
        exclude_border=False,
    )
    marqueurs = np.zeros(mnh.shape, dtype=np.int32)
    marqueurs[cimes[:, 0], cimes[:, 1]] = np.arange(1, len(cimes) + 1)
    masque = mnh > HAUTEUR_MIN_HOUPPIER
    etiquettes = watershed(-lisse, marqueurs, mask=masque)

    # suppression des houppiers trop petits
    surfaces = np.bincount(etiquettes.ravel()) * grille.res**2
    trop_petits = np.where(surfaces < SURFACE_MIN_HOUPPIER)[0]
    etiquettes[np.isin(etiquettes, trop_petits)] = 0
    ids = np.unique(etiquettes)
    ids = ids[ids > 0]
    log.info("%d arbres détectés", len(ids))
    return etiquettes, ids


def caracteristiques(points: dict, hauteur: np.ndarray, etiquettes: np.ndarray, ids: np.ndarray,
                     mnh: np.ndarray, grille: Grille) -> dict[int, dict]:
    """Indicateurs LiDAR par arbre : forme du houppier, distribution verticale, intensité, retours."""
    l, c = grille.indices(points["x"], points["y"])
    veg = np.isin(points["classe"], VEGETATION) & (hauteur > 1.0)
    lab = etiquettes[l, c]
    sel = veg & (lab > 0)
    lab_s, h_s = lab[sel], hauteur[sel]
    int_s = points["intensite"][sel].astype(np.float32)
    ret_s, nbr_s = points["retour"][sel], points["nb_retours"][sel]

    ordre = np.argsort(lab_s, kind="stable")
    lab_s, h_s, int_s, ret_s, nbr_s = lab_s[ordre], h_s[ordre], int_s[ordre], ret_s[ordre], nbr_s[ordre]
    debuts = np.searchsorted(lab_s, ids)
    fins = np.searchsorted(lab_s, ids, side="right")

    objets = ndi.find_objects(etiquettes)
    res = {}
    for i, (d, f) in zip(ids, zip(debuts, fins)):
        sl = objets[i - 1]
        if sl is None:
            continue
        masque = etiquettes[sl] == i
        surface = masque.sum() * grille.res**2
        hm = mnh[sl][masque]
        # position de la cime : cellule la plus haute du houppier
        k = np.argmax(np.where(masque, mnh[sl], -1))
        lc, cc = np.unravel_index(k, masque.shape)
        xc, yc = grille.centre(sl[0].start + lc, sl[1].start + cc)
        lignes, cols = np.nonzero(masque)
        etendue_l = (lignes.max() - lignes.min() + 1) * grille.res
        etendue_c = (cols.max() - cols.min() + 1) * grille.res
        n = f - d
        h = h_s[d:f]
        if n < 15:
            continue
        hmax = float(np.percentile(h, 99))
        hist, _ = np.histogram(h / max(hmax, 1e-3), bins=10, range=(0, 1))
        p = hist / max(hist.sum(), 1)
        entropie = float(-(p[p > 0] * np.log(p[p > 0])).sum() / np.log(10))
        it = int_s[d:f]
        res[int(i)] = {
            "x": xc, "y": yc,
            "hauteur": round(float(hm.max()), 2),
            "h_p99": hmax,
            "h_p90": float(np.percentile(h, 90)),
            "h_p75": float(np.percentile(h, 75)),
            "h_p50": float(np.percentile(h, 50)),
            "h_p25": float(np.percentile(h, 25)),
            "h_p10": float(np.percentile(h, 10)),
            "h_moy": float(h.mean()),
            "h_ecart": float(h.std()),
            "rapport_base": float(np.percentile(h, 10) / max(hmax, 1e-3)),
            "entropie": entropie,
            "surface": round(float(surface), 2),
            "diametre": round(float(2 * np.sqrt(surface / np.pi)), 2),
            "allongement": float(max(etendue_l, etendue_c) / max(min(etendue_l, etendue_c), grille.res)),
            "compacite": float(surface / max(etendue_l * etendue_c, 1e-3)),
            "densite": float(n / surface),
            "int_moy": float(it.mean()),
            "int_ecart": float(it.std()),
            "int_p90": float(np.percentile(it, 90)),
            "part_premiers": float((ret_s[d:f] == 1).mean()),
            "part_uniques": float((nbr_s[d:f] == 1).mean()),
            "retours_moy": float(nbr_s[d:f].mean()),
            "volume": float(hm.sum() * grille.res**2),
        }
    log.info("%d arbres avec indicateurs LiDAR", len(res))
    return res
