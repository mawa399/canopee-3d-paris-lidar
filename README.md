# Canopée 3D de Paris — LiDAR HD et machine learning

Du nuage de points **LiDAR HD de l'IGN** à un inventaire 3D interactif des arbres : chaque arbre du parc des Buttes-Chaumont et des rues voisines est **détecté dans le LiDAR**, son **genre est prédit par machine learning**, et le résultat est **comparé à l'inventaire de la Ville de Paris**.

**Démo en ligne :** https://mawa399.github.io/canopee-3d-paris-lidar/

Réalisé avec Python (laspy, scikit-image, scikit-learn) et **ArcGIS Maps SDK for JavaScript 5.1**.

## Ce que fait le projet

- **22 millions de points LiDAR** traités sur 110 ha (4 dalles LiDAR HD)
- **Détection individuelle des arbres** : modèle numérique de terrain, modèle de hauteur de canopée, détection des cimes et délimitation de chaque houppier
- **Appariement** des arbres détectés avec l'inventaire municipal (genre, espèce, hauteur, circonférence)
- **Classification du genre** et **estimation de la circonférence** à partir de 27 indicateurs LiDAR par arbre
- **Validation spatiale** : les arbres testés sont dans des blocs de 150 m jamais vus pendant l'entraînement
- **Application 3D** : arbres en 3D réalistes par genre, filtres, mode « vérification » (prédiction juste / fausse), fiche de chaque arbre et **affichage de son nuage de points**

## Résultats

| Indicateur | Valeur |
|---|---|
| Arbres détectés | 3 306 |
| Appariés à l'inventaire | 1 870 |
| Genre (10 classes) — bonnes réponses | 43 % (modèle naïf : 29 %) |
| Genre — F1 macro | 0,39 |
| Genre le mieux reconnu | Platane (F1 0,71) |
| Circonférence — erreur moyenne | 35 cm (R² 0,53) |
| Hauteur LiDAR vs inventaire | écart moyen 3,2 m, corrélation 0,70 |

Les valeurs exactes de la dernière exécution sont dans l'application (bloc « Le modèle de machine learning »).

**Limite principale.** Les dalles ont été acquises en **mars 2023, avant la feuillaison** : les feuillus sont sans feuilles, ce qui rend les genres difficiles à distinguer. Les persistants (if, pin) et le platane sont les mieux reconnus. La **transparence hivernale du houppier** (part du laser qui atteint le sol sous l'arbre) ressort parmi les indicateurs les plus utiles. Combiner le LiDAR avec de l'imagerie (orthophotos infrarouges, Sentinel-2) améliorerait nettement la classification.

## Chaîne de traitement

```
LiDAR HD IGN (WFS → dalles COPC)        Inventaire « Les arbres » (API Open Data Paris)
            │                                          │
   découpe de la zone                                  │
            │                                          │
  MNT (points sol) ─► MNH (végétation haute, 0,5 m)    │
            │                                          │
  cimes (maxima locaux) ─► houppiers (watershed)       │
            │                                          │
  27 indicateurs par arbre ◄──── appariement ──────────┘
            │
  forêt aléatoire : genre + circonférence, validation croisée spatiale
            │
  GeoJSON + nuages de points binaires ─► application ArcGIS Maps SDK for JavaScript
```

| Fichier | Rôle |
|---|---|
| [`pipeline/telechargement.py`](pipeline/telechargement.py) | Liste des dalles (WFS IGN), téléchargement, découpe ; arbres de l'Open Data |
| [`pipeline/traitement.py`](pipeline/traitement.py) | MNT, MNH, segmentation des arbres, indicateurs LiDAR |
| [`pipeline/apprentissage.py`](pipeline/apprentissage.py) | Appariement, modèles, validation spatiale, prédictions |
| [`pipeline/run.py`](pipeline/run.py) | Orchestration et export des fichiers web |
| [`src/main.ts`](src/main.ts) | Application 3D (SceneView, GeoJSONLayer, WebStyleSymbol, FeatureLayer client) |

Le pipeline tourne dans **GitHub Actions** à chaque mise à jour : il télécharge les données, entraîne les modèles, construit l'application et la publie sur GitHub Pages.

## Seconde chaîne : ArcGIS Pro et ArcGIS Online

Le même LiDAR a été traité une seconde fois avec **ArcGIS Pro 3.7** (Spatial Analyst, 3D Analyst), et les résultats sont publiés sur **ArcGIS Online**, d'où l'application les lit en direct (bloc « Chaîne ArcGIS Pro · ArcGIS Online »).

| Étape | Outils ArcGIS Pro |
|---|---|
| Nuage de points | Jeu de données LAS (COPC), filtre par classes IGN |
| Hauteur de la végétation | LAS Dataset To Raster (classes 4-5, max, 0,5 m) moins le MNT IGN |
| Cimes et houppiers | Focal Statistics (maxima locaux, rayon 3 m), Region Group, Flow Direction et Watershed sur la canopée inversée |
| Indicateurs | Zonal Statistics As Table, LAS Point Statistics As Raster (densité, part des retours dans la végétation), intensité moyenne, distance à la rue (BD TOPO) et à l'arbre voisin |
| Machine learning | Classification et régression basées sur une forêt : groupe d'essence (4 groupes) et circonférence |
| Publication | Couche d'entités hébergée (arbres) ; Create Point Cloud Scene Layer Package puis couche de scène hébergée (16,8 millions de points) |

| Résultat (ArcGIS Pro) | Valeur |
|---|---|
| Arbres détectés | 5 279 |
| Appariés à l'inventaire | 2 320 |
| Groupe d'essence (4 groupes) — bonnes réponses en validation | 59 % |
| Circonférence — R² en validation / erreur moyenne | 0,45 / 36 cm |
| Hauteur LiDAR vs inventaire | écart médian 2,1 m, corrélation 0,67 |
| Taux de canopée de la zone (végétation > 2 m) | 26 % |

Les deux chaînes ne prédisent pas la même cible (10 genres côté Python, 4 groupes côté ArcGIS Pro) ni avec la même validation (blocs spatiaux côté Python, tirage aléatoire de 25 % côté ArcGIS Pro) : leurs scores ne se comparent donc pas directement.

- Couche des arbres : [Arbres_Canopee3D_Paris](https://www.arcgis.com/home/item.html?id=1171618aa47b4fd998f0c52840f322d2)
- Couche du nuage de points : [Nuage_Vegetation_ButtesChaumont](https://www.arcgis.com/home/item.html?id=35e1fc2f601b4f97b3319d09976f29b9)
- Script arcpy reprenant toutes les étapes : [`pipeline_arcgis/canopee_arcgis.py`](pipeline_arcgis/canopee_arcgis.py)

## Côté SDK JavaScript

- `SceneView` avec terrain et ombres portées
- `GeoJSONLayer` alimentée par les résultats du pipeline, filtres par `definitionExpression`
- Arbres en 3D : `WebStyleSymbol` (`EsriRealisticTreesStyle`) par genre, dimensionnés par variables visuelles (hauteur et diamètre du houppier)
- Mode thématique et mode vérification : `UniqueValueRenderer` sur symboles 3D
- Nuage de points d'un arbre : `FeatureLayer` côté client alimentée par `applyEdits`, couleur selon la hauteur
- Nuage de points complet : `PointCloudLayer` hébergée sur ArcGIS Online, rendus couleurs réelles, altitude et classe
- Arbres de la chaîne ArcGIS Pro : `FeatureLayer` hébergée, symboles 3D dimensionnés et fenêtre contextuelle
- Interface : Calcite Design System

## Lancer en local

```bash
pip install -r requirements.txt
python pipeline/run.py      # environ 2 min, télécharge ~800 Mo de LiDAR
npm install
npm run dev
```

## Données et licences

- **LiDAR HD** © IGN — Licence Ouverte Etalab 2.0
- **Les arbres** © Ville de Paris — ODbL
- Imagerie et terrain : Esri

Projet inspiré d'un prototype d'inventaire forestier urbain par LiDAR partagé par Lex Ivey.

Auteur : **Mawa Diaw** — géomaticien / développeur SIG · [LinkedIn](https://www.linkedin.com/in/mawa-diaw) · Licence du code : MIT
