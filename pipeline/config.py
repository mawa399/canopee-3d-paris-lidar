"""Paramètres du pipeline Canopée 3D de Paris."""
from pathlib import Path

# Zone d'étude : parc des Buttes-Chaumont et rues voisines (Lambert 93, EPSG:2154)
ZONE = {"xmin": 654200, "ymin": 6864200, "xmax": 655300, "ymax": 6865200}
NOM_ZONE = "Parc des Buttes-Chaumont et alentours (19e)"

# Sources
WFS_IGN = "https://data.geopf.fr/wfs/ows"
COUCHES_DALLES = [  # couches candidates du tableau d'assemblage LiDAR HD (on essaie dans l'ordre)
    "IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle",
    "IGNF_LIDAR-HD_TA:nuage-dalle",
]
API_ARBRES = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/les-arbres/exports/geojson"
)

# Traitement
RESOLUTION = 0.5          # taille de cellule des rasters (m)
HAUTEUR_MIN_ARBRE = 4.0   # hauteur minimale d'une cime (m)
HAUTEUR_MIN_HOUPPIER = 2.5
DISTANCE_MIN_CIMES = 3.0  # distance minimale entre deux cimes (m)
SURFACE_MIN_HOUPPIER = 4.0  # m²

# Apprentissage
MIN_ECHANTILLONS_GENRE = 40   # en dessous, le genre est regroupé dans « Autre »
TAILLE_BLOC_VALIDATION = 150  # m : blocs spatiaux pour la validation croisée

# Dossiers
RACINE = Path(__file__).resolve().parent.parent
CACHE = RACINE / "cache"
SORTIE = RACINE / "public" / "data"
