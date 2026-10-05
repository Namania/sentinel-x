import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") },
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
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
