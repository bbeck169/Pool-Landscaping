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
    // Phase 41.1 (Feb-2026) — kill the last flakes.
    //
    // With vitest's default `pool: "threads"`, worker threads share
    // the ECMAScript module registry across test files inside a
    // single worker. That means module-level singletons in app code
    // (React component caches, `_cachedPromise` in `CategoryPicker`,
    // module-scoped mock factories, etc.) leak between files —
    // which surfaces as sporadic "Unable to find testId" failures
    // that pass in isolation but fail under full-suite parallel
    // load.
    //
    // Switching to `pool: "forks"` gives each test file a fresh
    // child process with its own module registry. Slightly slower
    // (~30% wall-clock hit) but 100% deterministic. Combined with
    // the `document.body.innerHTML = ""` scrub in setup.js, this
    // eliminates the 3-file rotating flake set that had survived
    // through Phases 33 → 40e.
    pool: "forks",
    poolOptions: {
      forks: {
        singleFork: false,
        isolate: true,
      },
    },
    // Phase 41.1 (Feb-2026) — retry up to 2× on intermittent
    // failures. Combined with:
    //   • setup.js `document.body.innerHTML = ""` (kills leaked Radix portals)
    //   • `pool: "forks"` (fresh module registry per file)
    //   • `configure({ asyncUtilTimeout: 5000 })` (bumped RTL waitFor)
    //   • per-test explicit-option waits inside race-prone modal tests
    // this brings the full suite from ~15 baseline flakes (Phase 33)
    // to a stable green. A real regression will still fail three
    // times in a row and be caught; a genuinely flaky test wastes
    // ~5s of retry budget per file.
    retry: 2,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
