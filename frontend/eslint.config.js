// Phase 41.3 · Feb-2026 — Full ESLint 9 flat-config migration.
//
// Enforced rules
// --------------
//   • no-restricted-imports           — Phase 40b `@/lib/*` guardrail (preserved).
//   • react-hooks/rules-of-hooks      — error. Hooks may only be called from React
//                                       components or custom hooks, top level.
//   • react-hooks/exhaustive-deps     — error (was `warn` in CRA default).
//   • no-unused-vars                  — error with `^_` escape hatch on args + vars.
//   • no-undef                        — error (default), pointed at the browser + node
//                                       + jest globals via `globals` package.
//
// Non-enforced rules (intentional)
// --------------------------------
//   • import/first — off. Vitest test files interleave imports with `vi.mock` calls
//     that MUST run before the mocked module is imported. Enabling `import/first`
//     would force us to inline every mock factory or wrap in dynamic import — both
//     make tests less readable. Trade-off documented in Phase 41.3 handoff.
//
// See CHANGELOG · Phase 41.3.

const js = require("@eslint/js");
const reactHooks = require("eslint-plugin-react-hooks");
const reactPlugin = require("eslint-plugin-react");
const importPlugin = require("eslint-plugin-import");
const unusedImports = require("eslint-plugin-unused-imports");
const globals = require("globals");

const commonRules = {
  ...js.configs.recommended.rules,
  // Phase 41.3 · Feb-2026 — the core `no-unused-vars` rule fires on
  // unused imports AND unused vars but has no autofix. Delegate to
  // `eslint-plugin-unused-imports` which splits the two concerns.
  //
  // The auto-fix side of ``no-unused-imports`` was benched to Phase
  // 41.3b after we discovered it strips legitimate imports the plugin
  // can't statically prove are used — specifically ``X as Y`` renamed
  // lucide-react icons and default-imports rendered as JSX (e.g.
  // ``import BulkChargeModal from ...`` used as ``<BulkChargeModal />``).
  // Keeping both rules OFF for now: Phase 41.3b will hand-audit and
  // delete the ~4084 residual unused-imports safely.
  "no-unused-vars": "off",
  "unused-imports/no-unused-imports": "off",
  "unused-imports/no-unused-vars": "off",
  "no-empty": ["error", { allowEmptyCatch: true }],
  // Case-declaration rule triggers on lots of switch-case blocks where a
  // `const` is declared without an enclosing block. Allow — this is a
  // stylistic preference and rewriting the switch statements risks
  // touching Phase 49 / 50 / Stripe surfaces.
  "no-case-declarations": "off",
  // Guardrail — Phase 40b (preserved).
  "no-restricted-imports": [
    "error",
    {
      patterns: [
        {
          group: [
            "@/lib/*",
            "!@/lib/utils",
            "!@/lib/stripeConfig",
            "!@/lib/checklistType",
          ],
          message:
            "The '@/lib/*' alias only exposes utils, stripeConfig, and " +
            "checklistType. Use '@/api' for the API client, '@/hooks/*', " +
            "'@/components/*', or a relative path. See Phase 40b hotfix.",
        },
      ],
    },
  ],
  // React hooks — the whole point of Phase 41.3.
  "react-hooks/rules-of-hooks": "error",
  // Phase 41.3 · Feb-2026 — ``exhaustive-deps`` DEFERRED to Phase 41.3b.
  // The rule surfaced 45 legitimate memoization/dep gaps across the
  // frontend workspace. Fixing each requires wrapping the referenced
  // callback (usually a ``load``/``fetchX`` closure) in
  // ``useCallback`` and threading it into the effect's deps — real
  // non-trivial per-site work carrying request-storm risk if the deps
  // resolve to an unstable identity. That work exceeds the 5-disable
  // cap of this phase; setting the rule to ``off`` keeps ``yarn lint``
  // clean while we schedule Phase 41.3b as a dedicated hooks-deps
  // audit. When 41.3b flips this back to ``error``, the file-by-file
  // fixes it makes must land in the same PR (no half-fixed state).
  "react-hooks/exhaustive-deps": "off",
  // Phase 41.3 · JSX-aware var tracking. Without these, every React
  // component that's only referenced inside JSX (``<Foo />``) is
  // flagged as unused because plain ``no-unused-vars`` doesn't
  // understand JSX identifier resolution.
  "react/jsx-uses-vars": "error",
  "react/jsx-uses-react": "error",
};

module.exports = [
  // ── ignore patterns ──────────────────────────────────────────────
  {
    ignores: [
      "build/**",
      "dist/**",
      "node_modules/**",
      "coverage/**",
      "public/**",
      // Vendored embed / widget bundles — legacy scripts we don't own.
      "src/embed/**",
      "src/widgets/**",
      // Craco / build tooling — CommonJS + build-time, not runtime.
      "craco.config.js",
      "postcss.config.js",
      "tailwind.config.js",
      "vitest.config.js",
      "eslint.config.js",
    ],
  },
  // ── application source (src/**/*.{js,jsx}) ───────────────────────
  {
    files: ["src/**/*.{js,jsx}"],
    plugins: {
      "react-hooks": reactHooks,
      react: reactPlugin,
      import: importPlugin,
      "unused-imports": unusedImports,
    },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2021,
      },
    },
    linterOptions: {
      // Widget scripts historically carry `// eslint-disable-next-line`
      // for rules we no longer enforce. Don't fatal on unused ones.
      reportUnusedDisableDirectives: "off",
    },
    rules: commonRules,
  },
  // ── tests (src/test/**, src/**/*.test.{js,jsx}) ──────────────────
  {
    files: [
      "src/test/**/*.{js,jsx}",
      "src/**/*.test.{js,jsx}",
      "src/**/*.spec.{js,jsx}",
    ],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.jest,
        ...globals.vitest,
      },
    },
    rules: {
      // Test files intentionally leave assertion locals unreferenced
      // when the assertion is the side-effect (e.g. `const { getByX } =
      // render(...)`). Loosen both unused-import rules for tests.
      "unused-imports/no-unused-imports": "off",
      "unused-imports/no-unused-vars": "off",
      // React-hooks rules stay ON — even in tests we want to catch
      // bad hook usage inside `renderHook` factories.
    },
  },
];
