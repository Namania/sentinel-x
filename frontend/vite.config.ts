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
    // LAN-served SPA on a Raspberry Pi: one ~570 kB chunk (180 kB gzip) is acceptable; revisit if it grows.
    chunkSizeWarningLimit: 600,
  },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false },
});
