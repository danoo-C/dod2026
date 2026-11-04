// Vite: the dev server (./dod sim, ./dod dev) and the build (./dod frontend-build).
// In development the browser only talks to Vite; /api, /ws and /media go on
// to the backend, so cookies and the WebSocket work as they will in production,
// where the backend serves the build itself (docs/plans/frontend.md, step 1).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// ./dod sim passes the backend's container name; outside Docker it is local
const backend = process.env.DOD_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": backend,
      "/media": backend,
      "/ws": { target: backend, ws: true },
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets", // the backend serves /assets/* from here
    emptyOutDir: true,
  },
});
