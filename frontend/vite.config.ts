import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

// Dev proxy target: a local uvicorn by default, the `api` container under compose.dev.yml.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
const wsTarget = apiTarget.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: {
    proxy: {
      "/api": { target: apiTarget, rewrite: (p) => p.replace(/^\/api/, "") },
      "/ws": { target: wsTarget, ws: true },
    },
    // Bind mounts on some Docker setups do not forward file events; polling is the fallback.
    watch: { usePolling: process.env.VITE_USE_POLLING === "true" },
  },
  build: {
    // LAN-served SPA on a Raspberry Pi: the app chunk stays around 300 kB (gzip < 100 kB).
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        // React and the router change rarely: a separate chunk keeps them cached across redeploys.
        codeSplitting: {
          groups: [
            {
              name: "vendor",
              test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/,
            },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Dates rendered in tests must not depend on the machine's time zone.
    env: { TZ: "Europe/Paris" },
  },
});
