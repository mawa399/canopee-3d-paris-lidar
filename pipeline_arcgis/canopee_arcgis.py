"""
Canopée 3D de Paris — chaîne ArcGIS Pro / ArcGIS Online.

Reprend, dans un seul script, les étapes exécutées dans ArcGIS Pro 3.7 (licence Advanced,
extensions Spatial Analyst et 3D Analyst) pour produire les couches publiées sur ArcGIS Online :
  1. téléchargement des dalles LiDAR HD (IGN), des MNT/MNH et de l'inventaire « Les arbres » ;
  2. modèle de hauteur de la végétation (points classés 4 et 5) à 50 cm ;
  3. détection des cimes (maxima locaux) et houppiers (bassins versants sur la canopée inversée) ;
  4. indicateurs par houppier (hauteurs, forme, densité et intensité LiDAR, contexte) ;
  5. appariement un à un avec l'inventaire de la Ville de Paris ;
  6. forêts aléatoires (Classification et régression basées sur une forêt) : groupe d'essence et circonférence ;
  7. publication : couche d'entités des arbres et couche de scène du nuage de points.

À lancer depuis la fenêtre Python d'ArcGIS Pro (ou propy.bat), connecté à ArcGIS Online.
"""

import glob
import json
import math
import os
import shutil
import urllib.parse
import urllib.request
import zipfile

import arcpy
from arcpy.sa import (Con, FlowDirection, FocalStatistics, IsNull, NbrCircle, Raster,
                      RegionGroup, Watershed, ZonalStatisticsAsTable)

BASE = os.path.join(os.path.expanduser("~"), "Documents", "Canopee3DParis")
GDB = os.path.join(BASE, "canopee.gdb")
L93 = arcpy.SpatialReference(2154)
WGS84 = arcpy.SpatialReference(4326)
CENTRE_PARC = (2.3828, 48.8806)          # parc des Buttes-Chaumont (lon, lat)
DEMI_LARGEUR, DEMI_HAUTEUR = 650, 500     # emprise d'étude : 1,3 km x 1,0 km
WFS = "https://data.geopf.fr/wfs/ows"

arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Spatial")
arcpy.CheckOutExtension("3D")


def telecharger(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 10_000:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Canopee3DParis/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest + ".part", "wb") as fo:
        shutil.copyfileobj(r, fo, 1 << 20)
    os.replace(dest + ".part", dest)


# ---------------------------------------------------------------------------
# 1. Données
# ---------------------------------------------------------------------------
def etape_donnees():
    for d in ["data/laz", "data/mnh", "data/mnt", "data/opendata", "out"]:
        os.makedirs(os.path.join(BASE, d), exist_ok=True)
    if not arcpy.Exists(GDB):
        arcpy.management.CreateFileGDB(BASE, "canopee.gdb")

    c = arcpy.PointGeometry(arcpy.Point(*CENTRE_PARC), WGS84).projectAs(L93).firstPoint
    aoi = [round(c.X - DEMI_LARGEUR), round(c.Y - DEMI_HAUTEUR), round(c.X + DEMI_LARGEUR), round(c.Y + DEMI_HAUTEUR)]
    json.dump({"aoi_l93": aoi}, open(os.path.join(BASE, "aoi.json"), "w"))

    # Dalles LiDAR HD qui recouvrent l'emprise (catalogue de la Géoplateforme)
    e = arcpy.Extent(*aoi, spatial_reference=L93).projectAs(WGS84)
    url = (f"{WFS}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAME=IGNF_LIDAR-HD_METADONNEE:metadata"
           f"&outputFormat=application/json&SRSName=EPSG:4326&count=50&BBOX={e.YMin},{e.XMin},{e.YMax},{e.XMax}")
    for f in json.loads(urllib.request.urlopen(url, timeout=60).read())["features"]:
        p = f["properties"]
        nom = p["coordonnees_nw"]
        telecharger(p["url_npl"], os.path.join(BASE, "data/laz", os.path.basename(p["url_npl"])))
        telecharger(p["url_mnt"], os.path.join(BASE, "data/mnt", f"MNT_{nom}.tif"))
        telecharger(p["url_mnh"], os.path.join(BASE, "data/mnh", f"MNH_{nom}.tif"))

    # Inventaire « Les arbres » de la Ville de Paris (avec une marge de 100 m)
    w = arcpy.Extent(aoi[0] - 100, aoi[1] - 100, aoi[2] + 100, aoi[3] + 100, spatial_reference=L93).projectAs(WGS84)
    where = f"in_bbox(geo_point_2d, {w.YMin:.6f}, {w.XMin:.6f}, {w.YMax:.6f}, {w.XMax:.6f})"
    telecharger("https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/les-arbres/exports/geojson?where="
                + urllib.parse.quote(where), os.path.join(BASE, "data/opendata", "arbres_paris.geojson"))

    # Tronçons de route de la BD TOPO (indicateur « distance à la rue »)
    b = f"{aoi[0]-50},{aoi[1]-50},{aoi[2]+50},{aoi[3]+50},urn:ogc:def:crs:EPSG::2154"
    telecharger(f"{WFS}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=BDTOPO_V3:troncon_de_route"
                f"&OUTPUTFORMAT=application/json&SRSNAME=EPSG:2154&COUNT=5000&BBOX={b}",
                os.path.join(BASE, "data", "routes_bdtopo.geojson"))
    return aoi


# ---------------------------------------------------------------------------
# 2-3. Canopée et segmentation des arbres
# ---------------------------------------------------------------------------
def etape_segmentation(aoi):
    arcpy.env.workspace = GDB
    tifs = glob.glob(os.path.join(BASE, "data", "mnt", "*.tif"))
    arcpy.management.MosaicToNewRaster(tifs, GDB, "mnt_mosaic", L93, "32_BIT_FLOAT", 0.5, 1, "MAXIMUM")
    arcpy.management.Clip("mnt_mosaic", " ".join(map(str, aoi)), "mnt", "#", "-9999", "NONE", "NO_MAINTAIN_EXTENT")

    lasd = os.path.join(BASE, "out", "lidar_hd.lasd")
    arcpy.management.CreateLasDataset(glob.glob(os.path.join(BASE, "data/laz", "*.laz")), lasd, "NO_RECURSION",
                                      None, L93, "COMPUTE_STATS", "ABSOLUTE_PATHS")
    arcpy.env.extent = arcpy.Extent(*aoi)
    arcpy.env.snapRaster = os.path.join(GDB, "mnt")
    arcpy.env.cellSize = 0.5

    # Le MNH de l'IGN contient aussi les bâtiments : on repart des seuls points de végétation (classes 4 et 5)
    arcpy.management.MakeLasDatasetLayer(lasd, "veg_haute", class_code=[4, 5])
    arcpy.conversion.LasDatasetToRaster("veg_haute", "veg_dsm", "ELEVATION", "BINNING MAXIMUM NONE", "FLOAT", "CELLSIZE", 0.5)
    chm = Raster("veg_dsm") - Raster("mnt")
    Con(IsNull(chm), 0, Con(chm < 0, 0, chm)).save("chm_veg")

    # Cimes : maxima locaux (rayon 3 m) d'une canopée lissée, au-dessus de 5 m
    lisse = FocalStatistics(Raster("chm_veg"), NbrCircle(2, "CELL"), "MEAN")
    lisse.save("chm_lisse2")
    cimes = Con((lisse == FocalStatistics(lisse, NbrCircle(6, "CELL"), "MAXIMUM")) & (lisse >= 5), 1)
    RegionGroup(cimes, "EIGHT").save("sommets_id")

    # Houppiers : bassins versants de la canopée inversée, limités à la végétation de plus de 2 m
    masque = Con(lisse >= 2, lisse)
    bassins = Con(masque >= 2, Watershed(FlowDirection(-masque, "FORCE"), "sommets_id", "VALUE"))
    bassins.save("houppiers_r")
    arcpy.conversion.RasterToPolygon("houppiers_r", "houppiers_brut", "NO_SIMPLIFY", "Value", "MULTIPLE_OUTER_PART")
    arcpy.management.Dissolve("houppiers_brut", "houppiers", "gridcode")
    arcpy.management.FeatureToPoint("houppiers", "houppiers_pts", "INSIDE")
    return lasd


# ---------------------------------------------------------------------------
# 4. Indicateurs par houppier
# ---------------------------------------------------------------------------
def etape_indicateurs(lasd):
    arcpy.env.workspace = GDB
    arcpy.management.MakeLasDatasetLayer(lasd, "veg", class_code=[3, 4, 5])
    arcpy.management.MakeLasDatasetLayer(lasd, "tous")
    arcpy.management.LasPointStatsAsRaster("veg", "n_veg", "POINT_COUNT", "CELLSIZE", 1)
    arcpy.management.LasPointStatsAsRaster("tous", "n_tous", "POINT_COUNT", "CELLSIZE", 1)
    arcpy.conversion.LasDatasetToRaster("veg", "int_veg", "INTENSITY", "BINNING AVERAGE NONE", "FLOAT", "CELLSIZE", 1)
    # Part des retours dans la végétation : élevée pour les persistants, faible pour les feuillus nus en mars
    (arcpy.sa.Float(Raster("n_veg")) / arcpy.sa.Float(Raster("n_tous"))).save("frac_veg")

    fc = "houppiers"
    arcpy.management.CalculateGeometryAttributes(fc, [["surface_m2", "AREA"]], area_unit="SQUARE_METERS")
    for ras, stat, pre, cols in [("chm_veg", "ALL", "h", ["MAX", "MEAN", "STD"]), ("n_veg", "MEAN", "dens", ["MEAN"]),
                                 ("frac_veg", "MEAN", "frac", ["MEAN"]), ("int_veg", "ALL", "int", ["MEAN", "STD"])]:
        ZonalStatisticsAsTable("houppiers_r", "VALUE", ras, f"zs_{pre}", "DATA", stat)
        arcpy.management.JoinField(fc, "gridcode", f"zs_{pre}", "VALUE", cols)
        for c in cols:
            arcpy.management.AlterField(fc, c, f"{pre}_{c.lower()}", f"{pre}_{c.lower()}")
    arcpy.management.CalculateField(fc, "diametre_m", "2*math.sqrt(!surface_m2!/math.pi)", "PYTHON3", field_type="DOUBLE")
    arcpy.management.CalculateField(fc, "elancement", "!h_max!/max(!diametre_m!,0.5)", "PYTHON3", field_type="DOUBLE")

    # Contexte : distance à la rue (BD TOPO, voies carrossables) et à l'arbre voisin
    routes = json.load(open(os.path.join(BASE, "data", "routes_bdtopo.geojson"), encoding="utf-8"))
    arcpy.management.CreateFeatureclass(GDB, "routes", "POLYLINE", spatial_reference=L93)
    arcpy.management.AddField("routes", "nature", "TEXT")
    with arcpy.da.InsertCursor("routes", ["SHAPE@", "nature"]) as cur:
        for f in routes["features"]:
            g = f["geometry"]
            parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
            arr = arcpy.Array([arcpy.Array([arcpy.Point(*c[:2]) for c in p]) for p in parts])
            cur.insertRow([arcpy.Polyline(arr, L93), f["properties"].get("nature")])
    arcpy.management.MakeFeatureLayer("routes", "rues", "nature IN ('Route à 1 chaussée', 'Route à 2 chaussées', 'Rond-point')")
    arcpy.analysis.GenerateNearTable("houppiers_pts", "rues", "near_rue", "", "NO_LOCATION", "NO_ANGLE", "CLOSEST")
    arcpy.analysis.GenerateNearTable("houppiers_pts", "houppiers_pts", "near_vois", "", "NO_LOCATION", "NO_ANGLE", "CLOSEST")
    pt2h = dict(arcpy.da.SearchCursor("houppiers_pts", ["OBJECTID", "ORIG_FID"]))
    drue = {pt2h[a]: d for a, d in arcpy.da.SearchCursor("near_rue", ["IN_FID", "NEAR_DIST"])}
    dvois = {pt2h[a]: d for a, d in arcpy.da.SearchCursor("near_vois", ["IN_FID", "NEAR_DIST"])}
    for n in ["dist_rue", "dist_voisin"]:
        arcpy.management.AddField(fc, n, "DOUBLE")
    with arcpy.da.UpdateCursor(fc, ["OBJECTID", "dist_rue", "dist_voisin"]) as cur:
        for oid, _, _ in cur:
            cur.updateRow([oid, drue.get(oid, 500.0), dvois.get(oid)])


# ---------------------------------------------------------------------------
# 5. Appariement avec l'inventaire
# ---------------------------------------------------------------------------
CONIFERES = {"Taxus", "Pinus", "Cedrus", "Picea", "Abies", "Thuja", "Chamaecyparis", "Sequoia", "Sequoiadendron",
             "Cupressus", "Juniperus", "Cryptomeria", "Pseudotsuga", "Tsuga", "Calocedrus", "Cupressocyparis",
             "Cephalotaxus", "Araucaria"}


def groupe(genre):
    if genre is None:
        return None
    if genre == "Platanus":
        return "Platane"
    if genre == "Aesculus":
        return "Marronnier"
    return "Conifère persistant" if genre in CONIFERES else "Autre feuillu"


def etape_appariement():
    arcpy.env.workspace = GDB
    arcpy.env.extent = None
    g = json.load(open(os.path.join(BASE, "data/opendata", "arbres_paris.geojson"), encoding="utf-8"))
    champs = ["idbase", "domanialite", "libellefrancais", "genre", "espece", "circonferenceencm", "hauteurenm"]
    arcpy.management.CreateFeatureclass(GDB, "arbres_odp", "POINT", spatial_reference=L93)
    for n, t in zip(champs, ["LONG", "TEXT", "TEXT", "TEXT", "TEXT", "LONG", "LONG"]):
        arcpy.management.AddField("arbres_odp", n, t)
    with arcpy.da.InsertCursor("arbres_odp", ["SHAPE@"] + champs) as cur:
        for f in g["features"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            p = f["properties"]
            row = [arcpy.PointGeometry(arcpy.Point(lon, lat), WGS84).projectAs(L93)] + [p.get(c) for c in champs]
            row[6] = int(row[6]) if isinstance(row[6], (int, float)) else None
            row[7] = int(row[7]) if isinstance(row[7], (int, float)) else None
            cur.insertRow(row)

    # Appariement glouton un à un, du couple le plus proche au plus éloigné, dans un rayon de 4 m
    arcpy.analysis.GenerateNearTable("houppiers_pts", "arbres_odp", "near_tab", "4 Meters", "NO_LOCATION", "NO_ANGLE", "ALL", 5)
    paires = sorted((d, h, a) for h, a, d in arcpy.da.SearchCursor("near_tab", ["IN_FID", "NEAR_FID", "NEAR_DIST"]))
    pris_h, pris_a, match = set(), set(), {}
    for d, h, a in paires:
        if h not in pris_h and a not in pris_a:
            pris_h.add(h); pris_a.add(a); match[h] = a
    odp = {r[0]: r[1:] for r in arcpy.da.SearchCursor("arbres_odp", ["OBJECTID", "idbase", "genre", "espece", "libellefrancais",
                                                                     "circonferenceencm", "hauteurenm", "domanialite"])}
    pt2h = dict(arcpy.da.SearchCursor("houppiers_pts", ["OBJECTID", "ORIG_FID"]))
    mh = {pt2h[h]: odp[a] for h, a in match.items()}
    noms = ["odp_id", "odp_genre", "odp_espece", "odp_nom", "odp_circ", "odp_haut", "odp_domaine", "groupe"]
    for n, t in zip(noms, ["LONG", "TEXT", "TEXT", "TEXT", "LONG", "LONG", "TEXT", "TEXT"]):
        arcpy.management.AddField("houppiers", n, t)
    with arcpy.da.UpdateCursor("houppiers", ["OBJECTID"] + noms) as cur:
        for row in cur:
            v = mh.get(row[0])
            cur.updateRow([row[0]] + (list(v) + [groupe(v[1])] if v else [None] * 8))


# ---------------------------------------------------------------------------
# 6. Machine learning (forêt aléatoire d'ArcGIS Pro)
# ---------------------------------------------------------------------------
VARIABLES = ["h_max", "h_mean", "h_std", "surface_m2", "diametre_m", "elancement", "dens_mean", "frac_mean",
             "int_mean", "int_std", "dist_rue", "dist_voisin"]


def etape_apprentissage():
    arcpy.env.workspace = GDB
    expl = [[v, "false"] for v in VARIABLES]
    match = [[v, v] for v in VARIABLES]
    arcpy.management.MakeFeatureLayer("houppiers", "appr_groupe", "groupe IS NOT NULL")
    r = arcpy.stats.Forest("PREDICT_FEATURES", "appr_groupe", "groupe", "CATEGORICAL", expl,
                           features_to_predict="houppiers", output_features="pred_groupe", explanatory_variable_matching=match,
                           output_importance_table="importance_groupe", number_of_trees=300, percentage_for_training=25,
                           output_validation_table="valid_groupe", compensate_sparse_categories=False, number_validation_runs=3)
    open(os.path.join(BASE, "out", "forest_groupe.txt"), "w", encoding="utf-8").write(r.getMessages())

    arcpy.management.MakeFeatureLayer("houppiers", "appr_circ", "odp_circ > 10 AND odp_circ < 600")
    r = arcpy.stats.Forest("PREDICT_FEATURES", "appr_circ", "odp_circ", None, expl,
                           features_to_predict="houppiers", output_features="pred_circ", explanatory_variable_matching=match,
                           number_of_trees=300, percentage_for_training=25, output_validation_table="valid_circ",
                           number_validation_runs=3)
    open(os.path.join(BASE, "out", "forest_circ.txt"), "w", encoding="utf-8").write(r.getMessages())


# ---------------------------------------------------------------------------
# 7. Publication sur ArcGIS Online
# ---------------------------------------------------------------------------
def etape_publication(aoi, lasd):
    from arcgis.gis import GIS
    gis = GIS("pro")
    arcpy.env.workspace = GDB

    # Couche des arbres (assemblage des indicateurs et des prédictions), publiée depuis une géodatabase compressée
    pg = {r[0]: (r[1], r[2]) for r in arcpy.da.SearchCursor("pred_groupe", ["SOURCE_ID", "PREDICTED", "PRED_PROB"])}
    pc = dict(arcpy.da.SearchCursor("pred_circ", ["SOURCE_ID", "PREDICTED"]))
    pts = {oid: shp for shp, oid in arcpy.da.SearchCursor("houppiers_pts", ["SHAPE@", "ORIG_FID"])}
    pub = os.path.join(BASE, "out", "publication")
    shutil.rmtree(pub, ignore_errors=True)
    os.makedirs(pub)
    gdb_pub = arcpy.management.CreateFileGDB(pub, "Arbres_Canopee3D_Paris.gdb")[0]
    fc = arcpy.management.CreateFeatureclass(gdb_pub, "Arbres_Canopee3D_Paris", "POINT", spatial_reference=L93)[0]
    champs = [("hauteur_m", "DOUBLE"), ("diam_houppier_m", "DOUBLE"), ("surface_houppier_m2", "DOUBLE"), ("dist_rue_m", "DOUBLE"),
              ("groupe_predit", "TEXT"), ("proba_groupe", "DOUBLE"), ("circ_estimee_cm", "LONG"), ("inventaire", "SHORT"),
              ("groupe_inventaire", "TEXT"), ("genre", "TEXT"), ("espece", "TEXT"), ("nom_francais", "TEXT"),
              ("circ_inventaire_cm", "LONG"), ("hauteur_inventaire_m", "LONG"), ("domanialite", "TEXT"), ("id_inventaire", "LONG")]
    for n, t in champs:
        arcpy.management.AddField(fc, n, t)
    src = ["OBJECTID", "h_max", "diametre_m", "surface_m2", "dist_rue", "groupe", "odp_genre", "odp_espece", "odp_nom",
           "odp_circ", "odp_haut", "odp_domaine", "odp_id"]
    with arcpy.da.InsertCursor(fc, ["SHAPE@"] + [c[0] for c in champs]) as cur:
        for oid, h, d, s, dr, grp, ge, es, nom, ci, ha, dom, idb in arcpy.da.SearchCursor("houppiers", src):
            if oid in pts:
                gp, pp = pg.get(oid, (None, None))
                cp = pc.get(oid)
                cur.insertRow([pts[oid], round(min(h, 40), 1), round(d, 1), round(s, 1), round(dr, 1), gp,
                               None if pp is None else round(pp, 2), None if cp is None else int(round(cp)),
                               1 if idb else 0, grp, ge, es, nom, ci, ha, dom, idb])
    zp = os.path.join(BASE, "out", "Arbres_Canopee3D_Paris_gdb.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(gdb_pub):
            for f in files:
                if not f.endswith(".lock"):
                    z.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), pub))
    dossier = gis.content.folders.get()
    source = dossier.add(item_properties={"title": "Arbres_Canopee3D_Paris_source", "type": "File Geodatabase"}, file=zp).result()
    couche = source.publish(publish_parameters={"name": "Arbres_Canopee3D_Paris", "maxRecordCount": 6000}, file_type="fileGeodatabase")

    # Nuage de points : sol et végétation de l'emprise, en paquet de couche de scène (I3S) publié en couche hébergée
    arcpy.management.MakeLasDatasetLayer(lasd, "veg_sol", class_code=[2, 3, 4, 5])
    cible = os.path.join(BASE, "out", "veg_aoi")
    os.makedirs(cible, exist_ok=True)
    lasd_aoi = os.path.join(BASE, "out", "veg_aoi.lasd")
    arcpy.ddd.ExtractLas("veg_sol", cible, " ".join(map(str, aoi)), None, "PROCESS_EXTENT", "_aoi", "MAINTAIN_VLR",
                         "REARRANGE_POINTS", "COMPUTE_STATS", lasd_aoi, "NO_COMPRESSION")
    slpk = os.path.join(BASE, "out", "Nuage_Vegetation_ButtesChaumont.slpk")
    arcpy.management.CreatePointCloudSceneLayerPackage(lasd_aoi, slpk, WGS84, None, "INTENSITY;RGB;CLASS_CODE;RETURNS",
                                                       0, 0.01, 0.01, None, "2.x")
    paquet = dossier.add(item_properties={"title": "Nuage_Vegetation_ButtesChaumont_slpk", "type": "Scene Package"}, file=slpk).result()
    scene = paquet.publish()

    for item in (couche, scene):
        item.sharing.sharing_level = "EVERYONE"
    print("Arbres :", couche.layers[0].url)
    print("Nuage de points :", scene.url)


if __name__ == "__main__":
    zone = etape_donnees()
    las = etape_segmentation(zone)
    etape_indicateurs(las)
    etape_appariement()
    etape_apprentissage()
    etape_publication(zone, las)
