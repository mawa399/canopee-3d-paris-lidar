import { defineConfig } from "vite";

// base relative : l'application fonctionne aussi bien sur GitHub Pages que dans un sous-dossier.
export default defineConfig({
  base: "./",
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 4000,
  },
});
