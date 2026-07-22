import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Phase 9B · Feb 2026 — Vitest harness for the marketing frontend.
// Kept intentionally minimal — CRA is still the runtime bundler, this
// is only for unit-testing pure React components without a full E2E.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.test.{js,jsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
