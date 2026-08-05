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
    // Phase 41.5 · Feb-2026 — Task W (forgot-password) was ported
    // to vitest and passes 3/3 under the vitest runner. Tasks OO
    // (admin-page mount-safety) and PP (portal service-reports hint)
    // remain Jest-only: both mount full-fat admin/portal pages whose
    // transitive dep graph (`@/components/ui-kit` + `@/api` +
    // `@/theme` + `react-router-dom` + `sonner` + `lucide-react` +
    // page-side hooks) hangs vitest's collection phase indefinitely
    // in this repo's config (verified with ``--pool=threads`` and
    // ``--no-file-parallelism`` — same hang). They still run under
    // ``craco test`` (Jest CRA) which resolves the graph faster.
    // Excluded here so they don't show up as 0-test collection
    // failures. A future Phase 41.5b can attack the root cause
    // (likely a large ``useEffect`` init in one of the ui-kit
    // components).
    exclude: [
      "**/node_modules/**",
      "src/test/phase34-admin-page-mount-safety.test.jsx",
      "src/test/phase34-task-pp-portal-hint.test.jsx",
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
    // Phase 41.4 · Feb-2026 — coverage gate. The gate lives at
    // ``yarn test:coverage`` and is called from CI on every PR. The
    // thresholds are baseline-minus-buffer, calibrated once from a
    // clean run (see ``PHASE41_4_COVERAGE_BASELINE.md``). Regressions
    // trip the gate; incremental improvements land silently.
    //
    // Excluded paths — anything that isn't runtime-testable source:
    //   * ``src/test/**``          — the test suite itself.
    //   * ``src/**/*.test.{js,jsx}`` — colocated test files.
    //   * ``src/index.js``         — CRA bootstrap; hits react-dom.
    //   * ``src/embed/**`` + ``src/widgets/**`` — vendored bundles
    //     already excluded from lint (Phase 41.3).
    //   * ``src/assets/**``        — Lottie JSONs + static imports.
    //   * ``src/nav/**`` + barrel index files — declarative maps
    //     with no branching logic to exercise.
    //   * ``**/*.d.ts`` + type-only files.
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "lcov"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{js,jsx}"],
      exclude: [
        "src/test/**",
        "src/**/*.test.{js,jsx}",
        "src/**/*.spec.{js,jsx}",
        "src/index.js",
        "src/embed/**",
        "src/widgets/**",
        "src/assets/**",
        "src/nav/**",
        "src/**/index.{js,jsx}",
        "**/*.d.ts",
      ],
      // Baseline (Phase 41.4 · Feb-2026 · observed clean run):
      //   statements 21.17% · branches 64.64% · functions 42.63% ·
      //   lines 21.17%.
      // Thresholds set 2-3 pp BELOW baseline so the gate trips on
      // regressions but tolerates the odd flaky test. Incremental
      // improvements should raise the floor in a follow-up phase
      // (Phase 41.4b — "raise the floor" — not scheduled).
      thresholds: {
        statements: 18,
        branches: 62,
        functions: 39,
        lines: 18,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
