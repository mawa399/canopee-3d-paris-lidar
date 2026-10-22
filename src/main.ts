import "@arcgis/core/assets/esri/themes/dark/main.css";
import "@esri/calcite-components/main.css";
import "./style.css";

import "@esri/calcite-components/components/calcite-shell";
import "@esri/calcite-components/components/calcite-shell-panel";
import "@esri/calcite-components/components/calcite-panel";
import "@esri/calcite-components/components/calcite-block";
import "@esri/calcite-components/components/calcite-button";
import "@esri/calcite-components/components/calcite-chip";
import "@esri/calcite-components/components/calcite-segmented-control";
import "@esri/calcite-components/components/calcite-segmented-control-item";
import "@esri/calcite-components/components/calcite-switch";
import "@esri/calcite-components/components/calcite-label";
import "@esri/calcite-components/components/calcite-slider";
import "@esri/calcite-components/components/calcite-link";
import "@esri/calcite-components/components/calcite-loader";

import EsriMap from "@arcgis/core/Map";
import SceneView from "@arcgis/core/views/SceneView";
import Basemap from "@arcgis/core/Basemap";
import Ground from "@arcgis/core/Ground";
import TileLayer from "@arcgis/core/layers/TileLayer";
import ElevationLayer from "@arcgis/core/layers/ElevationLayer";
import GeoJSONLayer from "@arcgis/core/layers/GeoJSONLayer";
import FeatureLayer from "@arcgis/core/layers/FeatureLayer";
import PointCloudLayer from "@arcgis/core/layers/PointCloudLayer";
import Graphic from "@arcgis/core/Graphic";
import Point from "@arcgis/core/geometry/Point";
import WebStyleSymbol from "@arcgis/core/symbols/WebStyleSymbol";
import UniqueValueRenderer from "@arcgis/core/renderers/UniqueValueRenderer";
import type GeoJSONLayerView from "@arcgis/core/views/layers/GeoJSONLayerView";

import { GENRES, infoGenre } from "./genres";

const $ = (id: string) => document.getElementById(id) as any;
const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const pct = (v: number) => `${Math.round(v * 100)} %`;
const echapper = (t: unknown) =>
  String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

// ---------------------------------------------------------------------------
// Chargement des données produites par le pipeline
// ---------------------------------------------------------------------------
const [arbresGeo, houppiersGeo, metriques, index, nuages] = await Promise.all([
  fetch("./data/arbres.geojson").then((r) => r.json()),
  fetch("./data/houppiers.geojson").then((r) => r.json()),
  fetch("./data/metriques.json").then((r) => r.json()),
  fetch("./data/nuages_index.json").then((r) => r.json()),
  fetch("./data/nuages.bin").then((r) => r.arrayBuffer()),
]);
const pointsArbres = new Int16Array(nuages);
const classes: string[] = metriques.genre.classes;

// Verdict de vérification : la prédiction est comparée au genre de l'inventaire (regroupé comme dans le modèle)
const parId = new Map<number, any>();
for (const f of arbresGeo.features) {
  const p = f.properties;
  const obs = p.genre_obs ? (classes.includes(p.genre_obs) ? p.genre_obs : "Autre") : null;
  p.genre_obs_classe = obs;
  p.verdict = obs == null ? "absent" : obs === p.genre_predit ? "juste" : "faux";
  p.inventaire = p.apparie ? 1 : 0;
  parId.set(p.id, f);
}
for (const f of houppiersGeo.features) {
  const a = parId.get(f.properties.id);
  f.properties.hauteur = a?.properties.hauteur ?? 0;
}
const versBlob = (o: unknown) => URL.createObjectURL(new Blob([JSON.stringify(o)], { type: "application/json" }));

// ---------------------------------------------------------------------------
// Rendus des arbres
// ---------------------------------------------------------------------------
const tailles = [
  { type: "size", axis: "height", field: "hauteur", valueUnit: "meters" },
  { type: "size", axis: "width-and-depth", field: "diametre", valueUnit: "meters" },
];

function rendu(mode: string) {
  if (mode === "realiste") {
    return new UniqueValueRenderer({
      field: "genre_predit",
      defaultSymbol: new WebStyleSymbol({ styleName: "EsriRealisticTreesStyle", name: "Unknown" }),
      uniqueValueInfos: classes.map((g) => ({
        value: g,
        label: infoGenre(g).nom,
        symbol: new WebStyleSymbol({ styleName: "EsriRealisticTreesStyle", name: infoGenre(g).modele3d }),
      })),
      visualVariables: tailles as any,
    });
  }
  const objet = (couleur: string) =>
    ({
      type: "point-3d",
      symbolLayers: [{ type: "object", resource: { primitive: "sphere" }, material: { color: couleur }, anchor: "bottom" }],
    }) as any;
  if (mode === "genre") {
    return new UniqueValueRenderer({
      field: "genre_predit",
      defaultSymbol: objet("#9aa3ad"),
      uniqueValueInfos: classes.map((g) => ({ value: g, label: infoGenre(g).nom, symbol: objet(infoGenre(g).couleur) })),
      visualVariables: tailles as any,
    });
  }
  return new UniqueValueRenderer({
    field: "verdict",
    uniqueValueInfos: [
      { value: "juste", label: "Prédiction juste", symbol: objet("#3fbf6f") },
      { value: "faux", label: "Prédiction fausse", symbol: objet("#e5484d") },
      { value: "absent", label: "Absent de l'inventaire", symbol: objet("#8a94a0") },
    ],
    visualVariables: tailles as any,
  });
}

const arbres = new GeoJSONLayer({
  url: versBlob(arbresGeo),
  title: "Arbres détectés",
  outFields: ["*"],
  elevationInfo: { mode: "on-the-ground" },
  renderer: rendu("realiste"),
});

const houppiers = new GeoJSONLayer({
  url: versBlob(houppiersGeo),
  title: "Houppiers",
  visible: false,
  opacity: 0.75,
  renderer: {
    type: "simple",
    symbol: { type: "polygon-3d", symbolLayers: [{ type: "fill", material: { color: "#5fbf7a" }, outline: { color: [20, 40, 25, 0.8], size: 0.6 } }] },
    visualVariables: [
      {
        type: "color",
        field: "hauteur",
        stops: [
          { value: 4, color: "#d9f0a3" },
          { value: 12, color: "#78c679" },
          { value: 20, color: "#238443" },
          { value: 30, color: "#004529" },
        ],
      },
    ],
  } as any,
});

const nuageLayer = new FeatureLayer({
  title: "Nuage de points de l'arbre",
  source: [],
  objectIdField: "oid",
  geometryType: "point",
  hasZ: true,
  spatialReference: { wkid: 4326 },
  fields: [
    { name: "oid", type: "oid" },
    { name: "h", type: "double" },
  ],
  elevationInfo: { mode: "relative-to-ground" },
  renderer: {
    type: "simple",
    symbol: { type: "point-3d", symbolLayers: [{ type: "object", resource: { primitive: "sphere" }, material: { color: "white" }, width: 0.35 }] },
    visualVariables: [
      {
        type: "color",
        field: "h",
        stops: [
          { value: 0, color: "#5b3a1e" },
          { value: 4, color: "#a6d96a" },
          { value: 12, color: "#1a9850" },
          { value: 25, color: "#00441b" },
        ],
      },
    ],
  } as any,
});

// ---------------------------------------------------------------------------
// Chaîne ArcGIS Pro : couches hébergées sur ArcGIS Online (publiques)
// ---------------------------------------------------------------------------
const AGOL_ARBRES = "https://services6.arcgis.com/XgSVk5L0bMP2HZ15/arcgis/rest/services/Arbres_Canopee3D_Paris/FeatureServer/0";
const AGOL_NUAGE = "https://tiles.arcgis.com/tiles/XgSVk5L0bMP2HZ15/arcgis/rest/services/Nuage_Vegetation_ButtesChaumont_slpk/SceneServer";

const rendusNuage: Record<string, any> = {
  rgb: { type: "point-cloud-rgb", field: "RGB", pointsPerInch: 25 },
  hauteur: {
    type: "point-cloud-stretch",
    field: "ELEVATION",
    pointsPerInch: 25,
    stops: [
      { value: 45, color: "#3b2a1a" },
      { value: 60, color: "#a6d96a" },
      { value: 75, color: "#1a9850" },
      { value: 95, color: "#00441b" },
    ],
  },
  classe: {
    type: "point-cloud-unique-value",
    field: "CLASS_CODE",
    pointsPerInch: 25,
    colorUniqueValueInfos: [
      { values: ["2"], label: "Sol", color: "#b08a5a" },
      { values: ["3"], label: "Végétation basse", color: "#c7e9a0" },
      { values: ["4"], label: "Végétation moyenne", color: "#5fbf7a" },
      { values: ["5"], label: "Végétation haute", color: "#1b6b3a" },
    ],
  },
};

const nuageAgol = new PointCloudLayer({
  url: AGOL_NUAGE,
  title: "Nuage de points LiDAR HD (ArcGIS Online)",
  visible: false,
  renderer: rendusNuage.rgb,
});

const arbresAgol = new FeatureLayer({
  url: AGOL_ARBRES,
  title: "Arbres détectés par ArcGIS Pro (ArcGIS Online)",
  visible: false,
  outFields: ["*"],
  elevationInfo: { mode: "on-the-ground" },
  renderer: {
    type: "simple",
    symbol: {
      type: "point-3d",
      symbolLayers: [{ type: "object", resource: { primitive: "cone" }, material: { color: "#f2b84b" }, anchor: "bottom" }],
    },
    visualVariables: [
      { type: "size", axis: "height", field: "hauteur_m", valueUnit: "meters" },
      { type: "size", axis: "width-and-depth", field: "diam_houppier_m", valueUnit: "meters" },
    ],
  } as any,
  popupEnabled: true,
  popupTemplate: {
    title: "Arbre détecté par ArcGIS Pro",
    content: [
      {
        type: "fields",
        fieldInfos: [
          { fieldName: "hauteur_m", label: "Hauteur LiDAR (m)" },
          { fieldName: "diam_houppier_m", label: "Diamètre du houppier (m)" },
          { fieldName: "groupe_predit", label: "Groupe d'essence prédit" },
          { fieldName: "proba_groupe", label: "Probabilité" },
          { fieldName: "circ_estimee_cm", label: "Circonférence estimée (cm)" },
          { fieldName: "nom_francais", label: "Inventaire : nom" },
          { fieldName: "circ_inventaire_cm", label: "Inventaire : circonférence (cm)" },
          { fieldName: "hauteur_inventaire_m", label: "Inventaire : hauteur (m)" },
        ],
      },
    ],
  } as any,
});

const carte = new EsriMap({
  basemap: new Basemap({
    baseLayers: [new TileLayer({ url: "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer" })],
  }),
  ground: new Ground({
    layers: [new ElevationLayer({ url: "https://elevation3d.arcgis.com/arcgis/rest/services/WorldElevation3D/Terrain3D/ImageServer" })],
  }),
  layers: [nuageAgol, houppiers, arbres, arbresAgol, nuageLayer],
});

const [lon0, lat0, lon1, lat1] = metriques.zone.emprise_wgs84;
const vue = new SceneView({
  container: "vue",
  map: carte,
  camera: {
    position: { longitude: (lon0 + lon1) / 2 - 0.0005, latitude: lat0 - 0.006, z: 650 },
    heading: 5,
    tilt: 62,
  },
  qualityProfile: "high",
  environment: {
    lighting: { type: "sun", date: new Date("2026-06-21T16:00:00+02:00"), directShadowsEnabled: true },
    atmosphereEnabled: true,
  } as any,
  popupEnabled: false,
  ui: { components: ["zoom", "compass", "navigation-toggle"] } as any,
});

// ---------------------------------------------------------------------------
// Panneau : la zone
// ---------------------------------------------------------------------------
const z = metriques.zone;
$("k-arbres").textContent = z.nb_arbres_detectes.toLocaleString("fr-FR");
$("k-canopee").textContent = pct(z.taux_canopee);
$("k-hauteur").textContent = `${nf.format(z.hauteur_moyenne)} m`;
$("k-points").textContent = `${nf.format(z.nb_points_lidar / 1e6)} M`;
$("texte-zone").textContent =
  `${z.nom}, ${nf.format(z.surface_ha)} ha. ${z.nb_apparies.toLocaleString("fr-FR")} arbres détectés ont été appariés aux ` +
  `${z.nb_arbres_inventaire.toLocaleString("fr-FR")} arbres de l'inventaire municipal. Cliquez sur un arbre pour voir sa fiche et son nuage de points.`;

// ---------------------------------------------------------------------------
// Filtres
// ---------------------------------------------------------------------------
const comptes = new Map<string, number>();
for (const f of arbresGeo.features) comptes.set(f.properties.genre_predit, (comptes.get(f.properties.genre_predit) ?? 0) + 1);
const genresActifs = new Set(classes);

for (const g of classes) {
  const chip = document.createElement("calcite-chip");
  chip.setAttribute("scale", "s");
  chip.setAttribute("interactive", "");
  chip.setAttribute("selected", "");
  chip.dataset.genre = g;
  chip.innerHTML = `<span class="pastille" style="background:${infoGenre(g).couleur}"></span>${echapper(infoGenre(g).nom)} <b>${comptes.get(g) ?? 0}</b>`;
  chip.addEventListener("click", () => {
    if (genresActifs.has(g)) genresActifs.delete(g);
    else genresActifs.add(g);
    chip.toggleAttribute("selected", genresActifs.has(g));
    appliquerFiltres();
  });
  $("genres").append(chip);
}

function appliquerFiltres() {
  const sl = $("sl-hauteur");
  const conditions = [
    `hauteur >= ${Number(sl.minValue)} AND hauteur <= ${Number(sl.maxValue)}`,
    genresActifs.size ? `genre_predit IN (${[...genresActifs].map((g) => `'${g}'`).join(",")})` : "1=0",
  ];
  if ($("sw-inventaire").checked) conditions.push("inventaire = 1");
  arbres.definitionExpression = conditions.join(" AND ");
  const visibles = arbresGeo.features.filter((f: any) => {
    const p = f.properties;
    return (
      p.hauteur >= sl.minValue && p.hauteur <= sl.maxValue && genresActifs.has(p.genre_predit) && (!$("sw-inventaire").checked || p.apparie)
    );
  }).length;
  $("compte-visible").textContent = `· ${visibles.toLocaleString("fr-FR")} affichés`;
}
$("sl-hauteur").addEventListener("calciteSliderChange", appliquerFiltres);
$("sw-inventaire").addEventListener("calciteSwitchChange", appliquerFiltres);
$("sw-houppiers").addEventListener("calciteSwitchChange", (e: any) => (houppiers.visible = e.target.checked));
$("mode").addEventListener("calciteSegmentedControlChange", (e: any) => {
  arbres.renderer = rendu(e.target.value);
  $("legende-verif").hidden = e.target.value !== "verif";
});
appliquerFiltres();

// Chaîne ArcGIS : interrupteurs et tableau de comparaison
$("sw-nuage-agol").addEventListener("calciteSwitchChange", (e: any) => {
  nuageAgol.visible = e.target.checked;
  $("rendu-nuage").hidden = !e.target.checked;
});
$("rendu-nuage").addEventListener("calciteSegmentedControlChange", (e: any) => {
  nuageAgol.renderer = rendusNuage[e.target.value];
});
$("sw-arbres-agol").addEventListener("calciteSwitchChange", (e: any) => {
  arbresAgol.visible = e.target.checked;
  // la fiche détaillée reste celle des arbres Python ; les arbres ArcGIS ont leur propre fenêtre contextuelle
  vue.popupEnabled = e.target.checked;
});
$("c-py-arbres").textContent = z.nb_arbres_detectes.toLocaleString("fr-FR");
$("c-py-apparies").textContent = z.nb_apparies.toLocaleString("fr-FR");
$("c-py-classes").textContent = `${classes.length} genres`;
$("c-py-precision").textContent = pct(metriques.genre.precision_globale);
$("c-py-r2").textContent = nf.format(metriques.circonference.r2);

// ---------------------------------------------------------------------------
// Panneau : le modèle
// ---------------------------------------------------------------------------
function barre(valeur: number, max: number, couleur: string) {
  return `<span class="barre"><i style="width:${Math.max(2, (valeur / max) * 100)}%;background:${couleur}"></i></span>`;
}
function afficherModele() {
  const g = metriques.genre;
  const c = metriques.circonference;
  const h = metriques.hauteur;
  const f1 = classes
    .map((k) => `<div class="ligne"><span>${echapper(infoGenre(k).nom)}</span>${barre(g.f1_par_classe[k], 1, infoGenre(k).couleur)}<b>${nf.format(g.f1_par_classe[k] * 100)}</b></div>`)
    .join("");
  const imp = metriques.importance_variables
    .slice(0, 6)
    .map((v: any) => `<div class="ligne"><span>${echapper(v.variable)}</span>${barre(v.importance, metriques.importance_variables[0].importance, "#5fbf7a")}</div>`)
    .join("");
  const maxConf = Math.max(...g.matrice_confusion.flat());
  const matrice = `<table class="matrice"><tr><th></th>${classes.map((k) => `<th title="${echapper(infoGenre(k).nom)}">${echapper(k.slice(0, 3))}</th>`).join("")}</tr>${g.matrice_confusion
    .map(
      (ligne: number[], i: number) =>
        `<tr><th title="${echapper(infoGenre(classes[i]).nom)}">${echapper(classes[i].slice(0, 3))}</th>${ligne
          .map((v, j) => `<td style="background:rgba(${i === j ? "95,191,122" : "229,72,77"},${(v / maxConf) ** 0.6})" title="${v}">${v || ""}</td>`)
          .join("")}</tr>`,
    )
    .join("")}</table>`;
  $("modele").innerHTML = `
    <p class="aide">Une forêt aléatoire prédit le <b>genre</b> de chaque arbre à partir de ${metriques.n_variables} indicateurs LiDAR
    (forme du houppier, distribution verticale des points, intensité, nombre de retours, transparence). Elle est entraînée sur les arbres appariés à l'inventaire.</p>
    <div class="chiffres">
      <div><span>${pct(g.precision_globale)}</span><small>de genres justes</small></div>
      <div><span>${pct(g.precision_hasard)}</span><small>modèle naïf</small></div>
      <div><span>${nf.format(c.mae_cm)} cm</span><small>erreur circonférence</small></div>
      <div><span>${nf.format(h?.ecart_moyen_m ?? 0)} m</span><small>écart de hauteur</small></div>
    </div>
    <p class="aide">${echapper(g.validation)}. Sur ${g.n_echantillons.toLocaleString("fr-FR")} arbres et ${classes.length} classes, F1 moyen : ${nf.format(g.f1_macro * 100)} / 100.
    Circonférence : R² ${nf.format(c.r2)} sur ${c.n_echantillons.toLocaleString("fr-FR")} arbres. Hauteur LiDAR vs inventaire : corrélation ${nf.format(h?.correlation ?? 0)}.</p>
    <p class="aide note">Le LiDAR a été acquis en mars 2023, avant la feuillaison : les feuillus sont sans feuilles, ce qui limite la séparation des genres.
    Les persistants (if, pin) et le platane, très reconnaissable, sont les mieux identifiés.</p>
    <p class="sous-titre">F1 par genre (sur 100)</p>${f1}
    <p class="sous-titre">Indicateurs les plus utiles</p>${imp}
    <p class="sous-titre">Matrice de confusion (lignes : inventaire, colonnes : prédiction)</p>${matrice}`;
}
afficherModele();

// ---------------------------------------------------------------------------
// Fiche d'un arbre et nuage de points
// ---------------------------------------------------------------------------
let arbreAffiche: number | null = null;

async function afficherNuage(f: any) {
  const id = f.properties.id;
  const entree = index[id];
  const existants = await nuageLayer.queryFeatures();
  const edits: any = { deleteFeatures: existants.features };
  if (entree) {
    const [debut, n] = entree;
    const [lon, lat] = f.geometry.coordinates;
    const mLon = 111320 * Math.cos((lat * Math.PI) / 180);
    const nouveaux = [];
    for (let k = 0; k < n; k++) {
      const o = (debut + k) * 3;
      const dx = pointsArbres[o] / 10, dy = pointsArbres[o + 1] / 10, h = pointsArbres[o + 2] / 10;
      nouveaux.push(
        new Graphic({
          geometry: new Point({ longitude: lon + dx / mLon, latitude: lat + dy / 110540, z: h }),
          attributes: { h },
        }),
      );
    }
    edits.addFeatures = nouveaux;
  }
  await nuageLayer.applyEdits(edits);
  arbres.opacity = entree ? 0.25 : 1;
  arbreAffiche = id;
  $("btn-nuage").textContent = "Masquer le nuage de points";
}

async function masquerNuage() {
  const existants = await nuageLayer.queryFeatures();
  await nuageLayer.applyEdits({ deleteFeatures: existants.features });
  arbres.opacity = 1;
  arbreAffiche = null;
}

function afficherFiche(f: any) {
  const p = f.properties;
  const pred = infoGenre(p.genre_predit);
  const verdict =
    p.verdict === "juste" ? `<span class="ok">✓ conforme à l'inventaire</span>`
      : p.verdict === "faux" ? `<span class="ko">✗ différent de l'inventaire</span>`
        : `<span class="neutre">arbre absent de l'inventaire</span>`;
  $("fiche").heading = `Arbre n° ${p.id}`;
  $("fiche-contenu").innerHTML = `
    <p class="sous-titre">Prédiction du modèle</p>
    <p class="genre-pred"><span class="pastille" style="background:${pred.couleur}"></span>${echapper(pred.nom)}
      <small>(${pct(p.confiance)} de confiance)</small></p>
    <p>${verdict}</p>
    ${p.apparie ? `<p class="sous-titre">Inventaire de la Ville de Paris</p>
      <p><b>${echapper(p.libelle_obs ?? p.genre_obs)}</b> <i>${echapper(p.genre_obs)} ${echapper(p.espece_obs ?? "")}</i><br><small>${echapper(p.domanialite ?? "")}</small></p>` : ""}
    <p class="sous-titre">Mesures</p>
    <table class="mesures">
      <tr><th></th><th>LiDAR</th><th>Inventaire</th></tr>
      <tr><td>Hauteur</td><td>${nf.format(p.hauteur)} m</td><td>${p.hauteur_obs ? nf.format(p.hauteur_obs) + " m" : "–"}</td></tr>
      <tr><td>Circonférence</td><td>${p.circ_predite} cm <small>(prédite)</small></td><td>${p.circ_obs ? p.circ_obs + " cm" : "–"}</td></tr>
      <tr><td>Houppier</td><td>${nf.format(p.diametre)} m de diamètre</td><td>–</td></tr>
      <tr><td>Surface</td><td>${nf.format(p.surface)} m²</td><td>–</td></tr>
    </table>
    <calcite-button id="btn-nuage" icon-start="point" width="full" appearance="outline">Voir le nuage de points</calcite-button>
    <p class="aide">Jusqu'à 400 points LiDAR du houppier, colorés selon leur hauteur.</p>`;
  $("panneau-arbre").collapsed = false;
  $("btn-nuage").addEventListener("click", async () => {
    if (arbreAffiche === p.id) {
      await masquerNuage();
      $("btn-nuage").textContent = "Voir le nuage de points";
    } else {
      await afficherNuage(f);
      vue.goTo({ target: new Point({ longitude: f.geometry.coordinates[0], latitude: f.geometry.coordinates[1] }), zoom: 20, tilt: 70 }, { duration: 1200 });
    }
  });
}

$("fiche").addEventListener("calcitePanelClose", async () => {
  $("panneau-arbre").collapsed = true;
  await masquerNuage();
});

vue.on("click", async (evt) => {
  const res = await vue.hitTest(evt, { include: [arbres] });
  const hit = res.results.find((r: any) => r.graphic?.layer === arbres) as any;
  if (!hit) return;
  const f = parId.get(hit.graphic.attributes.id);
  if (!f) return;
  if (arbreAffiche !== null && arbreAffiche !== f.properties.id) await masquerNuage();
  afficherFiche(f);
});

vue.whenLayerView(arbres).then((lv: GeoJSONLayerView) => {
  void lv;
  document.body.dataset.pret = "1";
});

// export pour le débogage dans la console
(window as any).app = { vue, arbres, GENRES };
