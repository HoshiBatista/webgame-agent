import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://localhost:8000",
      "/play": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
      "/readyz": "http://localhost:8000",
      "/docs": "http://localhost:8000",
      "/openapi.json": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.d.ts", "src/main.tsx", "src/types.ts"],
      thresholds: {
        lines: 70,
        functions: 70,
        statements: 70,
        branches: 60,
      },
    },
  },
});
