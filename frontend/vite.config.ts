/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
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
      "/comparisons": API,
      "/healthz": API,
      "/openapi.json": API,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    css: true,
    restoreMocks: true,
    setupFiles: ["src/test/setup.ts"],
    coverage: {
      provider: "v8",
      include: [
        "src/lib/**",
        "src/components/**",
        "src/panels/**",
        "src/routes/**",
      ],
      exclude: ["src/**/__tests__/**", "src/test/**"],
      thresholds: { lines: 80, functions: 80, branches: 75, statements: 80 },
    },
  },
});
