// Genres modélisés : nom français, couleur thématique et modèle 3D réaliste (style « EsriRealisticTreesStyle »).

export interface InfoGenre {
  nom: string;
  couleur: string;
  modele3d: string; // nom du symbole dans EsriRealisticTreesStyle
}

export const GENRES: Record<string, InfoGenre> = {
  Platanus: { nom: "Platane", couleur: "#e8b04a", modele3d: "Platanus" },
  Aesculus: { nom: "Marronnier", couleur: "#d9663f", modele3d: "Aesculus" },
  Acer: { nom: "Érable", couleur: "#c23b4c", modele3d: "Acer" },
  Taxus: { nom: "If", couleur: "#2f7d4f", modele3d: "Juniperus" },
  Corylus: { nom: "Noisetier", couleur: "#9a7b4f", modele3d: "Alnus" },
  Paulownia: { nom: "Paulownia", couleur: "#9b6fc9", modele3d: "Magnolia" },
  Robinia: { nom: "Robinier", couleur: "#7fbf5a", modele3d: "Robinia" },
  Prunus: { nom: "Prunus (cerisier, prunier…)", couleur: "#e989b5", modele3d: "Prunus" },
  Pinus: { nom: "Pin", couleur: "#1f5f6b", modele3d: "Pinus" },
  Tilia: { nom: "Tilleul", couleur: "#c7c94a", modele3d: "Tilia" },
  Fraxinus: { nom: "Frêne", couleur: "#6aa6c9", modele3d: "Fraxinus" },
  Quercus: { nom: "Chêne", couleur: "#7b5a2e", modele3d: "Quercus" },
  Autre: { nom: "Autre genre", couleur: "#9aa3ad", modele3d: "Unknown" },
};

export function infoGenre(genre: string | null | undefined): InfoGenre {
  return GENRES[genre ?? ""] ?? { nom: genre ?? "Inconnu", couleur: "#9aa3ad", modele3d: "Unknown" };
}
