import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy API calls to the ARCHON backend during development.
const API = process.env.ARCHON_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/repositories": API,
      "/runs": API,
      "/snapshots": API,
      "/components": API,
      "/healthz": API,
      "/openapi.json": API,
    },
  },
});
