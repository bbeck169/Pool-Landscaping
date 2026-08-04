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
    // Phase 33 · Feb 2026 — three Task PP/W/OO test files were intentionally
    // kept in Jest CJS syntax (`jest.mock(..., { virtual: true })`) and run
    // under `craco test`. Vitest can't collect them without a plugin rewrite;
    // exclude explicitly so they don't show up as 0-test collection failures.
    exclude: [
      "**/node_modules/**",
      "src/test/phase34-admin-page-mount-safety.test.jsx",
      "src/test/phase34-task-pp-portal-hint.test.jsx",
      "src/test/phase34-task-w-forgot-password.test.jsx",
    ],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
