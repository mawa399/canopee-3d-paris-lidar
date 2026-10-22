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

## Côté SDK JavaScript

- `SceneView` avec terrain et ombres portées
- `GeoJSONLayer` alimentée par les résultats du pipeline, filtres par `definitionExpression`
- Arbres en 3D : `WebStyleSymbol` (`EsriRealisticTreesStyle`) par genre, dimensionnés par variables visuelles (hauteur et diamètre du houppier)
- Mode thématique et mode vérification : `UniqueValueRenderer` sur symboles 3D
- Nuage de points d'un arbre : `FeatureLayer` côté client alimentée par `applyEdits`, couleur selon la hauteur
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
